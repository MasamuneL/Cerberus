# Entrenamiento y fine-tuning (CLI `cerberus_training`)

Guía operativa del pipeline descrito en [`PLAN_PIPELINE_FINETUNING.md`](PLAN_PIPELINE_FINETUNING.md).
Este documento crece con cada ticket FT; aquí se documenta lo que existe hoy.

## Estado

| Ticket | Contenido | Estado |
|---|---|---|
| FT0 | Paquete, configuración JSON estricta, CLI base, entorno CUDA fijado, comprobación de dispositivo | implementado |
| FT1 | `inventory`, `split` | implementado |
| FT2 | `prepare`, `preflight` | pendiente |
| FT3 | `train` (incluye `--dry-run` y `--resume`) | pendiente |
| FT4 | `evaluate`, `export` | pendiente |
| FT5 | `smoke --synthetic` y manual completo | pendiente |

Funcionan `validate` y `device` (FT0) e `inventory` y `split` (FT1). El resto de los subcomandos existe para que
`--help` muestre la interfaz prevista, valida la configuración si se pasa `--config` y termina con código 3 y un
mensaje `pendiente de FTn`. **No hay entrenamiento, evaluación ni modelo adaptado todavía**, y no se ha medido ninguna
duración ni consumo de recursos.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | correcto |
| 1 | `device --require-cuda` sin CUDA disponible |
| 2 | uso incorrecto de argumentos o configuración inválida/ilegible |
| 3 | subcomando todavía no implementado |
| 4 | dataset/inventario inutilizable (raíz inexistente o ilegible, salida dentro del dataset, dos rutas de E/S que son el mismo archivo, inventario ilegible o manipulado), pocos pacientes o `splits.json` existente incompatible |

## Uso con el entorno normal (CPU)

El entorno de la app (`uv sync`) instala el paquete en modo editable y sirve para `--help`, validar
configuraciones y ejecutar los tests. No necesita red ni GPU y no importa torch ni MONAI al arrancar la CLI.

```bash
uv sync
uv run python -m cerberus_training --help
uv run python -m cerberus_training train --help
uv run python -m cerberus_training validate --config configs/training/gtv_binary.json
uv run python -m cerberus_training device
```

## Configuración

El ejemplo versionado es [`configs/training/gtv_binary.json`](../configs/training/gtv_binary.json); el esquema
está en `backend/cerberus_training/config.py` (pydantic, `extra="forbid"`, `schema_version` obligatorio).
Una clave desconocida, una proporción de split que no suma 1, un valor no positivo o un SHA-256 mal formado
son errores, nunca se ignoran. Puntos a tener en cuenta:

- `paths.data_root` es el dataset externo, de solo lectura; todo lo generado va bajo `paths.work_dir`
  (por defecto `storage/training/`, ignorado por Git). Las rutas relativas se resuelven contra la raíz del repo.
- `weights.path` y `weights.sha256` son obligatorios y nunca se descargan en `train`. El valor del ejemplo es un
  **marcador de posición** (64 ceros): calcule el SHA-256 real de su `model.pt` con `shasum -a 256` antes de
  entrenar y sustitúyalo; las etapas posteriores rechazarán un hash que no coincida.
- Perfil de canales estricto `[T1c, T1, T2, FLAIR]`: T1 prefiere `t1eg` y luego `t1tse`; T2 exige `t2tse`.
  `t2star_policy` solo admite `disabled`: T2* no sustituye a T2.
- Las rutas `data_root`, `work_dir` y `weights.path` no pueden ser vacías ni `.`, y `work_dir` no puede coincidir
  con `data_root` ni estar dentro o contenerlo (tras resolver y normalizar), para no escribir sobre el dataset.
- Las semillas (`split.seed` y `seeds.*`) van de 0 a 2^32 - 1.
- `preprocess.patch_size` debe ser múltiplo de 8 en cada eje: SegResNet realiza 3 submuestreos (factor 2^3).
- El JSON se valida en modo estricto, sin coerciones: `true` no vale como entero, `"1e-4"` no vale como número,
  `96.0` no vale como tamaño de parche. El archivo debe ser UTF-8.
- `training.device` es `cpu` o `cuda`; `amp` exige `cuda`. Pedir `cuda` sin GPU fallará en `train`
  (FT3), no se degrada en silencio. El ejemplo usa `cuda` + AMP por ser el uso previsto.
- Los hiperparámetros por defecto (parche 96³, batch 1, acumulación 4, AdamW 1e-4, 100 épocas, paciencia 15)
  son un punto de partida, no un óptimo validado. El tamaño final de parche y el hardware necesario se
  decidirán con un piloto futuro.

`validate --write-resolved RUTA` guarda la configuración con rutas absolutas (nunca sobrescribe un archivo
existente); es el formato que cada run archivará como `config.resolved.json`.

## Inventario (`inventory`)

```bash
# Con rutas explícitas (no hace falta config)
uv run python -m cerberus_training inventory --data-root /ruta/CFB-GBM --output storage/training/inventory.jsonl
# O tomando paths.data_root y <paths.work_dir>/inventory.jsonl de la configuración (y su perfil de canales)
uv run python -m cerberus_training inventory --config configs/training/gtv_binary.json [--summary storage/training/inventory_summary.json]
```

Recorre el dataset externo **de solo lectura**, un estudio por vez. Valida con cabeceras NIfTI; además lee completos,
en streaming, los archivos seleccionados para su SHA-256, y decodifica solo los vóxeles de la GTV, para saber si
está vacía. Si un archivo cambia (identidad, tamaño o `mtime_ns`) entre la primera y la última apertura, el estudio
se excluye (`unreadable`). Imprime un resumen por paciente/tiempo (conteos, motivos de
exclusión, estratos, secuencia elegida por canal, duplicados y carpetas rechazadas); `--summary` lo guarda en JSON.
La salida se escribe de forma atómica (temporal, `fsync`, `os.replace` y `fsync` de la carpeta), no puede quedar
dentro de `data_root` y `--summary` no puede ser el mismo archivo que `--output`. Calcula el SHA-256 de cada archivo
seleccionado leyéndolo en bloques de 1 MiB, así que recorre todos los bytes de esos archivos (no se ha medido la
duración sobre la colección completa).

**Convención de nombres asumida** (adaptador `cerberus_v1`, `CerberusLayout` en `inventory.py`): la misma de
`Data/001` y de la API, `<data_root>/<paciente>/<tiempo>/<int(paciente)>_<tiempo>_<secuencia>.nii.gz`, p. ej.
`001/t0/1_t0_flair.nii.gz`. Paciente y tiempo se validan con `cerberus_api.sequences` antes de construir rutas;
carpetas con otro nombre se rechazan (`invalid_identifier`). Por privacidad, una carpeta rechazada nunca se
muestra por su nombre (podría ser un nombre real): el resumen, la salida estándar y `--summary` solo dan nivel
(`patient`/`timepoint`), el ID del paciente padre si es válido, el código y `name_sha8` (8 hex del SHA-256 del
nombre; para localizarla: `printf %s NOMBRE | shasum -a 256`). Los archivos que no siguen la convención (o que son
carpetas con nombre de secuencia) y archivos que no siguen la convención se cuentan en `unrecognized_files`. Una carpeta de estudio que no se puede listar produce un registro
excluido (`unreadable`) y una de paciente, un rechazo `unreadable`; solo una raíz ilegible aborta. Si la descarga de TCIA usa otra estructura, hay que escribir otro adaptador con la misma
interfaz (`name`, `file_name`, `parse_file`); no se relajan los validadores de la API.

Seguridad de rutas: cada ruta se resuelve siguiendo symlinks y debe quedar bajo la raíz; un symlink (carpeta o
archivo) que apunte fuera se rechaza. Los symlinks internos a la raíz se aceptan.

Perfil estricto: por canal se toma la **primera** secuencia presente en el orden de preferencia (`t1gd`; `t1eg` y
luego `t1tse`; `t2tse`; `flair`). Si ese archivo es inválido, el estudio se excluye: no se salta en silencio a la
siguiente preferencia. T2* nunca sustituye a T2. Sin GTV el estudio se excluye: nunca se crea una máscara vacía.

### Formato de `inventory.jsonl`

Una línea JSON por estudio (claves ordenadas), en orden (paciente, tiempo numérico):

| Campo | Contenido |
|---|---|
| `schema_version` | `1` |
| `study_id`, `patient`, `timepoint`, `timepoint_index` | `"001_t0"`, `"001"` (ID seudónimo de carpeta del dataset), `"t0"`, `0` |
| `stratum` | `baseline` (t0) o `follow_up` (solo descriptivo) |
| `layout` | adaptador de nombres usado (`cerberus_v1`) |
| `available_sequences`, `unrecognized_files` | secuencias reconocidas en la carpeta; nº de archivos ignorados |
| `channels` | `{T1c,T1,T2,FLAIR}` → `{sequence, path, shape, spacing_mm, affine, dtype, sha256}` o `null` |
| `selected_sequences` | secuencia realmente elegida por canal (o `null`) |
| `label` | GTV: mismos campos más `name: "gtv"`, `nonzero_voxels` y `empty`; `null` si falta o es inválida |
| `brain_mask` | máscara cerebral si existe y es válida; si no, `null` |
| `eligible` | `true` si no hay ninguna exclusión |
| `exclusions` | `[{code, message, channel?}]` |
| `review_flags` | `[{code, message, channel?}]`: no excluyen, pero hay que revisarlas antes de entrenar |

`path` es relativo a `data_root`; `spacing_mm` es el `pixdim` tal como está en el archivo (`nib.load` "repara" en
silencio los valores 0 o negativos, y el inventario no lo acepta). `read_inventory` no confía en el archivo:
revalida paciente/tiempo con `cerberus_api.sequences`, `study_id`, claves mínimas, rutas relativas sin `..` y
coherentes con `<paciente>/<tiempo>/`, SHA-256 bien formados, coherencia entre `eligible` y `exclusions`, y
`study_id` únicos; cualquier manipulación es un error claro (código 4). No se guarda ningún dato clínico ni DICOM.

Códigos de exclusión (estables): `missing_channel`, `missing_label`, `path_outside_root`, `not_a_file`, `unreadable`
(no es NIfTI-1, es NIfTI-2, cabecera dañada, vóxeles de la GTV ilegibles, carpeta del estudio ilegible o archivo
modificado durante el inventario), `not_3d` (incluye 4D con última dimensión 1), `invalid_shape`, `invalid_affine`
(no finito o |det| < 1e-6), `invalid_spacing` (no finito o ≤ 0) y `spacing_affine_mismatch` (`pixdim` difiere de
las normas de columna de `affine[:3,:3]` en más de rtol 1e-3; estricto a propósito, para que el remuestreo de FT2
no tenga que adivinar qué geometría es la buena). Señales de revisión: `empty_label`
(la GTV existe y está vacía; el estudio sigue elegible), `invalid_brain_mask` (se ignora la máscara) y
`duplicate_within_study`. En el resumen, las carpetas rechazadas llevan `invalid_identifier`, `path_outside_root` o
`unreadable`.

Lo que el inventario **no** valida (es de FT2, `prepare`): vóxeles finitos, GTV binaria, alineación entre canales y
la integridad de los vóxeles de las imágenes.

## Partición (`split`)

```bash
uv run python -m cerberus_training split --config configs/training/gtv_binary.json \
  [--inventory storage/training/inventory.jsonl] [--output storage/training/splits.json]
```

Solo usa estudios elegibles y agrupa todos los tiempos de cada paciente. Semilla y proporciones salen de
`split` en la configuración (por defecto 42 y 70/15/15). Algoritmo `largest_remainder_v1`:

1. Duplicados exactos: los pacientes que comparten el SHA-256 de algún **canal de imagen** se fusionan (union-find)
   y caen en la misma partición. GTV y máscaras no cuentan, porque dos máscaras vacías del mismo tamaño coinciden
   sin ser duplicados.
2. Cuotas de pacientes por resto mayor: la cuota `p·N` se redondea primero a 9 decimales (`round(p·N, 9)`, para que
   el error de coma flotante no convierta 0.15·20 = 3 en 2.9999999999999996), después `floor` y las unidades
   sobrantes a los mayores restos (empate → train, val, test). Si una partición queda en 0, toma 1 paciente de la mayor. Ejemplos: N=10 → 7/2/1, N=20 → 14/3/3,
   N=4 → 2/1/1.
3. Los grupos se ordenan por `sha256("<semilla>:<pacientes>")` y cada uno va a la partición con mayor déficit
   respecto a su cuota; si quedan tantos grupos como particiones vacías, se reservan para ellas. Con grupos
   fusionados, los tamaños reales pueden desviarse de la cuota (se reportan ambos). Si alguna partición se desvía más
   de `max(1, ceil(0.10·N))` pacientes, el split se escribe igualmente pero `warnings` lo explica y la CLI imprime
   `AVISO`; nunca se rompe un grupo de duplicados para reequilibrar. Revise ese aviso antes de entrenar.
4. Falla con menos de 3 pacientes elegibles o menos de 3 grupos independientes.

`splits.json` es **inmutable**: se publica de forma exclusiva (temporal completo + `os.link`, con permisos 0444; si
otro proceso lo publica antes, se recarga y se compara) y no puede quedar dentro de `data_root` ni coincidir con el
inventario. Si ya existe y coincide, se reutiliza. Si difiere
(otros registros elegibles, semilla o proporciones) o se editó a mano (su hash no cuadra), es un error: nunca se
redistribuye. Contiene `schema_version`, `group_by`, `seed`, `ratios`, `rounding`, `target_patients`,
`eligible_records_sha256` (hash canónico de los registros elegibles ordenados por `study_id`, no del archivo
`inventory.jsonl` completo), `eligible_studies`, `pretraining_overlap`,
`merged_groups`, `duplicates` (`{sha256, studies, partition}`), `partitions` (`{train,val,test}` →
`{patients, studies}`), `report`, `warnings` y `split_sha256` (hash canónico de todo lo anterior). `report` es solo
descriptivo: por partición da pacientes, estudios, estratos t0/seguimiento, secuencia elegida por canal, estudios
con máscara cerebral y GTV vacías.

`split.pretraining_overlap` (`unknown` por defecto) registra si alguien verificó que los pacientes no estén en el
preentrenamiento del bundle. Solo se pone `verified` tras hacer esa revisión; nunca se asume ausencia de solapamiento.

## Entorno CUDA independiente (`training-env/`)

Las ruedas de torch de la app apuntan al índice CPU en Linux (`pyproject.toml` raíz) y no deben cambiar.
Para entrenar en GPU se usa un proyecto `uv` aparte, [`training-env/`](../training-env/pyproject.toml), con su
propio `uv.lock` versionado:

- Depende del paquete `cerberus` por ruta (editable), de modo que ejecuta exactamente el mismo código.
- Fija `torch==2.14.1` y, en Linux y Windows, lo resuelve desde el índice `https://download.pytorch.org/whl/cu126`
  (`2.14.1+cu126`). En macOS no existe CUDA y se resuelve la rueda normal de PyPI.
- Un `override-dependencies` sustituye el requisito de torch del proyecto raíz (que lo dirigiría al índice CPU).
- No toca el `uv.lock` ni el `.venv/` de la app: su entorno virtual vive en `training-env/.venv/` (ignorado por Git).

Versiones elegidas el 2026-11-19: el índice `cu126` ofrece `2.14.1+cu126` y `cu130` ofrece `2.14.1+cu130`; `cu128`
no publica esa versión de torch. Se eligió **cu126** por requerir un controlador NVIDIA menos reciente. Las ruedas
de torch incluyen las bibliotecas CUDA, así que solo hace falta el controlador NVIDIA del sistema (consulte la
tabla de compatibilidad de NVIDIA para cu126). Si su controlador es reciente y prefiere `cu130`, cambie el nombre
y la URL del índice en `training-env/pyproject.toml` y regenere el lock.

```bash
# Instalar (reproducible; --locked falla si el lock no corresponde a los pyproject, en vez de ignorar la deriva)
uv sync --project training-env --locked

# Comprobar el dispositivo desde la raíz del repo (las rutas relativas de la config se resuelven contra el repo)
uv run --project training-env python -m cerberus_training device
uv run --project training-env python -m cerberus_training device --require-cuda   # código 1 si no hay GPU

# Ejecutar la CLI con CUDA
uv run --project training-env python -m cerberus_training validate --config configs/training/gtv_binary.json
```

`--locked` (y no `--frozen`) es deliberado: `training-env` depende del `pyproject.toml` raíz por ruta, así que
añadir o cambiar una dependencia de la app deja su lock desactualizado. `--frozen` instalaría igualmente el lock
viejo sin avisar; `--locked` aborta y obliga a ejecutar `uv lock --project training-env` y revisar el cambio.

**Advertencia sobre GPU recientes.** Las ruedas `cu126` solo incluyen kernels para ciertas arquitecturas (de
`sm_50` a `sm_90`, según la rueda); una GPU más nueva, como las RTX 50xx (Blackwell, `sm_120`), puede no
estar incluida y torch fallaría o avisaría al usarla. Ejecute `device` tras instalar: imprime la capability de
cada GPU y las arquitecturas compiladas, y añade un `AVISO` si la capability no está en la lista. En ese caso
cambie a un índice más nuevo (por ejemplo `cu130`, si ofrece la misma versión de torch) y regenere el lock.

Para regenerar el lock tras cambiar versiones (requiere red): `uv lock --project training-env`. Verifique
después con `uv lock --check --project training-env`.

`device` imprime versión de Python, plataforma, versión de torch, build CUDA, disponibilidad de CUDA, cuDNN,
bf16, nombre y capability de cada GPU, arquitecturas compiladas en la rueda y avisos; con `--json` emite el mismo informe en JSON. Nunca falla en una máquina sin GPU ni sin
torch (devuelve 0 salvo con `--require-cuda`). En el entorno de la app informará `torch con ruedas CPU`.

Nota: la instalación del entorno CUDA no se ha ejecutado en una máquina con GPU durante FT0 (el desarrollo se hizo
en macOS sin CUDA); solo se resolvió y fijó el lock. La primera comprobación real con GPU queda para el piloto.

## Tests

```bash
uv run pytest -q backend/tests/test_training_config.py backend/tests/test_training_cli.py \
  backend/tests/test_training_inventory.py backend/tests/test_training_splits.py
```

Cubren el esquema, la CLI, la ausencia de imports de torch/MONAI/nibabel al arrancar (y de nibabel/numpy en `split`), el inventario sobre NIfTI
sintéticos (affines y spacings distintos, canal faltante, solo T2*, GTV ausente o vacía, 4D, affine singular,
spacing no positivo, archivos dañados, traversal, symlinks e identificadores inválidos) y la partición
(determinismo, agrupación por paciente, duplicados, mínimos e inmutabilidad). No usan red, `Data/001` ni GPU.
