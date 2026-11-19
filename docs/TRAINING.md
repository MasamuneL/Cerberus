# Entrenamiento y fine-tuning (CLI `cerberus_training`)

Guía operativa del pipeline descrito en [`PLAN_PIPELINE_FINETUNING.md`](PLAN_PIPELINE_FINETUNING.md).
Este documento crece con cada ticket FT; aquí se documenta lo que existe hoy.

## Estado

| Ticket | Contenido | Estado |
|---|---|---|
| FT0 | Paquete, configuración JSON estricta, CLI base, entorno CUDA fijado, comprobación de dispositivo | implementado |
| FT1 | `inventory`, `split` | implementado |
| FT2 | `prepare`, `preflight`, transformaciones y caché | implementado |
| FT3 | `train` (incluye `--dry-run` y `--resume`), transferencia de SegResNet, artefactos del run | implementado |
| FT4 | `evaluate`, `export` | pendiente |
| FT5 | `smoke --synthetic` y manual completo | pendiente |

Funcionan `validate` y `device` (FT0), `inventory` y `split` (FT1), `prepare` y `preflight` (FT2) y `train` (FT3). El
resto de los subcomandos existe para que `--help` muestre la interfaz prevista, valida la configuración si se pasa
`--config` y termina con código 3 y un mensaje `pendiente de FTn`. El trainer solo se ha ejecutado con datos y pesos
sintéticos en CPU (tests): **no se ha hecho ningún fine-tuning real ni existe un modelo adaptado evaluado**, y no se ha
medido ninguna duración ni consumo de recursos (las cifras de `preflight` son estimaciones, no mediciones).

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | correcto |
| 1 | `device --require-cuda` o `train` con `training.device = "cuda"` sin CUDA disponible |
| 2 | uso incorrecto de argumentos o configuración inválida/ilegible |
| 3 | subcomando todavía no implementado |
| 4 | dataset/inventario inutilizable (raíz inexistente o ilegible, salida dentro del dataset, dos rutas de E/S que son el mismo archivo, inventario ilegible o manipulado), pocos pacientes, `splits.json` existente incompatible, o ningún estudio elegible en `prepare`/`preflight` |
| 5 | `prepare` terminó, pero al menos un estudio falló (los demás sí se prepararon; ver el informe) |
| 6 | recursos insuficientes: `prepare` se detiene por el límite de caché o el espacio libre; `preflight` estima que no cabe; `train` sin memoria (nunca reduce batch/parche) o `train --dry-run` sin disco para los checkpoints |
| 7 | `train`: pesos ausentes o con SHA-256 distinto, checkpoint incompatible (llaves faltantes/sobrantes, shapes), `freeze_modules` inválido o `--resume` rechazado |
| 8 | `train`: fallo numérico (NaN/Inf en pérdida, gradientes o predicción de validación) |

En `train`, el código 2 también cubre un `--run-id` inválido o ya existente (un run nunca se sobrescribe), un run en
uso por otro proceso (candado `.lock`) y límites de
FT3 (`preprocess.num_workers` distinto de 0 o caché desactivada); el 4, inventario/`splits.json`/caché inutilizables.

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

Lo que el inventario **no** valida (lo hace `prepare`, FT2): vóxeles finitos, GTV binaria, alineación entre canales y
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

## Preparación (`prepare`)

```bash
uv run python -m cerberus_training prepare --config configs/training/gtv_binary.json [--inventory RUTA]
```

Procesa **todos los estudios elegibles** del inventario (por defecto `<paths.work_dir>/inventory.jsonl`), ordenados
por `study_id` y **de uno en uno** (nunca carga la colección en RAM; las fuentes de un estudio se cargan y liberan de
una en una). Un error de un estudio se informa con su código y se sigue con el siguiente; al final la CLI devuelve 5
si hubo alguno. Un problema de recursos (límite de caché o disco) detiene el proceso con código 6. Sin estudios
elegibles, código 4. Siempre se escribe `<paths.work_dir>/prepare_report.json` de forma atómica, con o sin caché y
también si se aborta (`completed: false`, `aborted` con el motivo y el estudio en curso como `aborted`). Código en `backend/cerberus_training/transforms.py` (preparación y transformaciones) y
`cache.py` (caché y bucle de `prepare`).

Pasos por estudio (`prepare_study`):

1. **Fuentes.** Cada ruta del inventario se reconstruye a partir de identificadores revalidados con
   `cerberus_api.sequences` y se confina a `data_root`. Se recalcula el SHA-256 de cada archivo y debe coincidir con el
   del inventario (`source_changed` si no): si los datos cambian, hay que repetir `inventory`. Carga con `load_nifti()`.
2. **Geometría.** Referencia T1Gd (`T1c`). Cada canal, la GTV y la máscara cerebral deben ocupar el mismo espacio
   físico que la referencia: las 8 esquinas de su caja de vóxeles (por los bordes, en mm) deben coincidir con las de la
   referencia a ≤ `GEOMETRY_TOL_MM` = 0.5 mm (distancia de Hausdorff entre esquinas, independiente del orden de ejes).
   Se aceptan spacing, orientación, permutación o flips de ejes distintos que cubren la misma caja. Un desplazamiento,
   un FOV distinto o una rotación relativa se rechazan con `geometry_mismatch`: **el remuestreo no corrige desregistro**
   y estos casos requieren registro aparte. Esta comprobación solo ve cabeceras; un desregistro del contenido dentro de
   la misma caja no se puede detectar sin registrar.
3. **Grid destino.** Ortogonal RAS (diagonal positiva) de `preprocess.spacing_mm` (1 mm) que contiene la referencia,
   calculado con `nibabel.spaces.vox2out_vox` (el mismo criterio que `resample_to_output` en la inferencia de la API).
   Remuestreo con `scipy.ndimage.affine_transform` y `mode="grid-constant"` (fuera del FOV = 0, pero hasta el borde
   exterior de los vóxeles de borde se usa el vóxel: sin ceros espurios dentro del casco ni pérdida de una GTV en el
   plano de borde): imágenes lineal (orden 1), GTV y máscara cerebral vecino más próximo (orden 0, así que una máscara
   binaria sigue binaria). No se añadió ninguna dependencia.
4. **Soporte y normalización.** Con máscara cerebral, se multiplica por cada canal. Sin máscara (política
   `use_if_present`), el soporte son los vóxeles no nulos de algún canal y se registra la señal `no_brain_mask` (no
   hay skull-strip). Se recorta a la caja del soporte y cada canal se normaliza sobre sus vóxeles no nulos con
   `cerberus_api.segmentation.normalize_nonzero` (la misma función que la inferencia; un test fija su salida para
   detectar cambios en la API compartida). **La GTV nunca interviene en la normalización ni en el recorte, y nunca
   excluye un estudio por su posición** (sesgaría validación/prueba): los vóxeles de GTV fuera de la máscara cerebral,
   fuera del recorte o perdidos por el remuestreo se cuentan como señales de revisión. FT4 evalúa en el grid de
   referencia original, de modo que esos vóxeles perdidos cuentan allí como falsos negativos.

Salida: `image` float32 `[4, X, Y, Z]` en orden `[T1c, T1, T2, FLAIR]`, `label` (GTV) y `brain` (soporte usado) uint8
con valores {0, 1}, y la geometría (`reference_shape`, `reference_affine`, `prepared_shape`, `prepared_affine`,
`spacing_mm`). `restore_to_reference` lleva una máscara (o probabilidades, con orden 1) del grid preparado al grid
original de la T1c; la ida y vuelta de una GTV es exacta en grids alineados con spacing ≥ 1 mm (los vóxeles
fuente coinciden con centros del grid destino) y aproximada en oblicuos o con spacing no divisor de 1 mm.

Códigos de error de `prepare` (estables, `PREPARE_ERROR_CODES`):

| Código | Significado |
|---|---|
| `not_eligible` | el registro no es elegible (no debería llegar: `prepare` solo toma elegibles) |
| `invalid_source` | la ficha del inventario no corresponde a un archivo válido del estudio, o el registro está incompleto/manipulado |
| `source_changed` | el SHA-256 de una fuente no coincide con el inventario |
| `unreadable` | no se pudieron leer los vóxeles o la cabecera |
| `invalid_geometry` | volumen no 3D o affine no finito / no invertible |
| `geometry_mismatch` | canal, GTV o máscara no comparte espacio físico con la T1c (desregistro, FOV, affine) |
| `non_finite` | NaN o Inf en una imagen o máscara |
| `non_binary_label` | GTV con valores fuera de {0, 1}: **nunca se binariza en silencio** |
| `non_binary_mask` | máscara cerebral con valores fuera de {0, 1} |
| `empty_brain_mask` | máscara cerebral sin vóxeles |
| `empty_image` | un canal sin vóxeles no nulos dentro del soporte |

Señales de revisión (no impiden usar el estudio; el informe da por código los estudios y los vóxeles de GTV
implicados en `review_totals`):

| Señal | Significado |
|---|---|
| `empty_label` | la GTV existe y está vacía; se conserva vacía (sin GTV el inventario ya excluye: nunca se inventa una etiqueta) |
| `no_brain_mask` | sin máscara cerebral: soporte = vóxeles no nulos (política `use_if_present`), sin skull-strip |
| `label_outside_brain_mask` | `voxels` de GTV fuera de la máscara cerebral (se conservan si caen dentro del recorte) |
| `label_outside_support` | `voxels` de GTV fuera de la caja del soporte: se pierden del volumen preparado (`label_lost_voxels`) |
| `label_vanished` | la GTV tenía `voxels` en la fuente y quedó vacía tras el remuestreo |

### Transformaciones de entrenamiento

Funciones puras con un `numpy.random.Generator` sembrado (`make_rng(semilla, época, índice)`), que FT3 usará:

- `sample_patch`: parche `preprocess.patch_size` (96³ por defecto). Positivo (centro en la GTV) con probabilidad
  `pos/(pos+neg)` de `pos_neg_ratio` (1:1); negativo = **centro** en el soporte fuera de la GTV (el parche puede
  contener GTV en su periferia). GTV vacía → solo negativos. Si el volumen es menor que el parche en algún eje, se
  rellena con ceros al final de ese eje.
- `augment` (solo entrenamiento): intensidad por canal `x·a + b` con `a ∈ [0.9, 1.1]` y `b ∈ [-0.1, 0.1]` dentro del
  soporte, flip por eje con p = 0.5 y rotación de 90°·k con p = 0.5 en un plano de lados iguales. La GTV recibe las
  mismas transformaciones geométricas.
- `eval_sample` (validación/prueba/inferencia): volumen completo, sin augmentations ni recortes por GTV, con su
  geometría. La ventana deslizante es de FT3/FT4.

### Formato de la caché

```text
<paths.work_dir>/prepare_report.json   # último informe: completed, aborted, counts, review_totals, estado por estudio
<paths.work_dir>/cache/<preprocess_hash>/
  key.json              # componentes de la clave y hash completo
  <study_id>.npz        # image (float32), label (uint8), brain (uint8), meta (JSON en texto)
```

`preprocess_hash` son 16 hex del SHA-256 canónico de: `spacing_mm`, `orientation`, `brain_mask_policy`, orden de
canales/referencia/etiqueta, `TRANSFORMS_VERSION` (`ft2-v2`), `GEOMETRY_TOL_MM`, las versiones instaladas de numpy,
scipy y nibabel y la versión del esquema de caché. Cualquier cambio da otra carpeta y la anterior deja de usarse (no
se borra sola). El parche, el muestreo, las augmentations y los límites no forman parte de la clave porque no cambian
los volúmenes. Las fuentes tampoco: cada entrada guarda en `meta.sources` el SHA-256 de sus fuentes y solo es válida
si coincide con el del inventario actual, así que un cambio de datos invalida solo los estudios afectados (hay que
repetir `inventory` para que se detecte; en un fallo de caché `prepare` reverifica el SHA-256 de cada archivo).

`.npz` sin comprimir (`numpy.savez`), leído con `allow_pickle=False`. `meta` incluye `study_id`, `transforms_version`,
`channel_order`, `geometry`, `brain_mask_source`, `label_empty`, `label_voxels`, `label_lost_voxels`, `sources`,
`review_flags`, `preprocess_key` y `arrays` (SHA-256 de los bytes, dtype y shape de cada array). Un acierto exige clave,
`study_id`, fuentes y los tres SHA-256 de arrays (lee la entrada completa); `load()` lanza `CacheEntryError` explícito
si la entrada falta, es ilegible o no coincide, y `prepare` la reescribe. Cada estudio se escribe de forma atómica
(temporal en la misma carpeta, `fsync`, `os.replace`, `fsync` de la carpeta): un fallo a mitad no deja archivos
parciales, y los temporales `.*.tmp` huérfanos de una ejecución interrumpida se borran al empezar a escribir (se supone
un único `prepare` a la vez sobre el mismo `work_dir`). Antes de cada escritura se comprueba
que la carpeta `cache/` **completa** (claves antiguas incluidas) no supere `preprocess.cache_limit_gb` y que queden al
menos `preprocess.min_free_disk_gb` libres tras escribir; si no, `prepare` se detiene (código 6) pidiendo borrar
claves antiguas o subir el límite. Con `preprocess.cache_enabled = false`, `prepare` solo valida y no escribe caché
(sí el informe).

## Preflight (`preflight`)

```bash
uv run python -m cerberus_training preflight --config configs/training/gtv_binary.json [--inventory RUTA]
```

Informe en español, sin escribir nada, a partir de los shapes y affines de cabecera del inventario. **No usa el
tamaño comprimido de los `.nii.gz`** ni lo equipara con RAM:

- Disco de caché: vóxeles del grid destino (sin recorte, así que es una cota superior) × 18 bytes (4 canales float32
  + GTV + soporte uint8) + 64 KiB por estudio; total y estudio más grande.
- RAM pico de `prepare` por estudio (aprox.): 39 bytes por vóxel destino + 12 bytes por vóxel de la fuente más grande
  (cota de 8 bytes para el tipo nativo + copia float32). El grid destino se calcula desde `channels.reference`.
- RAM de datos por lote de entrenamiento (aprox.): estudio preparado más grande + `batch_size` parches × 18 bytes por
  vóxel × 3 copias. **No incluye activaciones ni gradientes de la red** (FT3).
- Espacio libre (`shutil.disk_usage` sobre `work_dir`), ocupación actual de `cache/` y de la clave actual, límite y
  margen, y estado informativo de los pesos (existencia y SHA-256; la verificación obligatoria es de `train`).

Devuelve 6 si la caché estimada más las claves antiguas supera `cache_limit_gb` o si lo que falta por escribir no
cabe dejando `min_free_disk_gb` libres; 4 si no hay estudios elegibles; si no, 0. Son estimaciones sin medir sobre la
colección real.

## Entrenamiento (`train`)

```bash
uv run python -m cerberus_training train --config configs/training/gtv_binary.json --dry-run
uv run python -m cerberus_training train --config configs/training/gtv_binary.json [--run-id NOMBRE]
uv run python -m cerberus_training train --config configs/training/gtv_binary.json \
  --resume storage/training/runs/<run_id>/checkpoints/last.pt
# En GPU, con el entorno CUDA independiente:
uv run --project training-env python -m cerberus_training train --config configs/training/gtv_binary.json --dry-run
```

Requisitos previos: `inventory`, `split` y `prepare` sobre el mismo `work_dir`. `train` lee
`<work_dir>/inventory.jsonl`, `<work_dir>/splits.json` (debe ser exactamente el que `split` calcularía hoy con ese
inventario y esa configuración; nunca se redistribuye) y la caché de `prepare` (`preprocess.cache_enabled = true`).
Código en `backend/cerberus_training/model.py`, `train.py` y `artifacts.py`.

### Transferencia de pesos (`model.py`)

1. `weights.path` debe existir y su SHA-256 coincidir con `weights.sha256` (**nunca se descarga nada**). El archivo se
   lee una sola vez: se calcula el SHA-256 de esos bytes y se cargan con `torch.load(io.BytesIO(...), weights_only=True)`
   (lo verificado es lo cargado). Debe ser un `state_dict` (llave → tensor), como el `model.pt` del bundle.
2. Se construye SegResNet de 3 salidas con la arquitectura de la API (4 entradas, `init_filters=16`,
   `blocks_down=(1,2,2,4)`, `blocks_up=(1,1,1)`, `dropout_prob=0.2`) y se carga con `strict=True`. Antes se comparan
   llaves y shapes: faltantes, sobrantes o shapes distintos dan un error que los enumera (código 7). Nunca `strict=False`.
3. Se reemplaza **solo** la proyección final. En MONAI 1.6.1 `SegResNet.conv_final` es
   `Sequential(GroupNorm, ReLU, Convolution(Conv3d(16 → 3, k=1)))`: la capa reemplazada es **`conv_final.2`**
   (`conv_final.2.conv.weight` `[3,16,1,1,1]` → `[1,16,1,1,1]` y `conv_final.2.conv.bias` `[3]` → `[1]`); la GroupNorm
   `conv_final.0` se transfiere. La capa nueva sale de una SegResNet de 1 salida construida con `seeds.head_init`
   dentro de `torch.random.fork_rng`: es determinista y no altera el generador global.
4. Se registran (en `provenance.json` → `transfer` y en cada checkpoint) los tensores transferidos, descartados y nuevos,
   con nombres y conteos. `training.freeze_modules` son prefijos de módulo (p. ej. `["convInit", "down_layers.0"]`):
   un prefijo que no corresponde a ningún parámetro, que incluye la cabeza nueva o que congela toda la red es un error.
   Los parámetros congelados no entran en el optimizador.

### Bucle

- Por época, los estudios de `train` se recorren en una permutación sembrada con `(seeds.training, época)`; cada lote
  toma `batch_size` parches de `train_sample` (FT2), cada uno de un estudio leído de la caché **de uno en uno**
  (verificando sus SHA-256) con `make_rng(seeds.augmentation, época, índice)`. Sin DataLoader: `num_workers` debe ser 0.
  Una época = un parche por estudio de train.
- Pérdida `dice_weight · DiceLoss(sigmoid=True) + bce_weight · BCEWithLogitsLoss` (MONAI/PyTorch) sobre el logit GTV;
  AdamW (`learning_rate`, `weight_decay`); sin scheduler. Acumulación de `grad_accum_steps` lotes por paso; la última
  ventana de una época puede ser más corta y se escala por su tamaño real.
- Validación cada `validate_every` épocas y en la última, sobre los volúmenes completos de `val` con
  `monai.inferers.sliding_window_inference` (ventana = `patch_size`, solapamiento 0.5, sin augmentations), umbral
  `sigmoid > training.threshold` (0.5) y `cerberus_api.segmentation.dice`. Métrica de selección: **Dice macro por
  paciente** (media de los tiempos de cada paciente y luego media de pacientes). `best` se guarda cuando el Dice mejora
  estrictamente; la parada temprana llega tras `early_stopping_patience` validaciones seguidas sin mejora.
- NaN/Inf en la pérdida, en los gradientes o en la predicción de validación detienen el run con código 8. Con AMP
  (solo `cuda`), un gradiente no finito es el mecanismo normal de `GradScaler`: el paso se salta y se cuenta en
  `amp_skipped_steps`. Sin memoria (`torch.OutOfMemoryError`/`MemoryError`): código 6; nunca se reduce batch ni parche.
- `training.device = "cuda"` sin GPU falla (código 1); nunca se degrada a CPU. AMP solo con `cuda` (ya lo exige el esquema).

**Determinismo.** Se siembran Python, NumPy y PyTorch con `seeds.training` (no hay workers que sembrar). Con
`seeds.deterministic` se activa `torch.use_deterministic_algorithms(True)` (en CUDA con `warn_only`, más
`cudnn.deterministic`, sin `benchmark` y `CUBLAS_WORKSPACE_CONFIG=:4096:8`). Al terminar (también ante errores) se
restaura todo el estado global tocado: generadores de Python, NumPy, PyTorch y CUDA, modos deterministas y
`CUBLAS_WORKSPACE_CONFIG`. En CPU es reproducible bit a bit: N épocas seguidas y k épocas + reanudar N−k dan los mismos pesos, estado del
optimizador y métricas (test). En CUDA no se garantiza: el backward del upsample trilineal de SegResNet no tiene versión
determinista y AMP añade variación. Estos límites se escriben en `provenance.json` → `determinism_limits`.

### Artefactos del run

```text
<paths.work_dir>/runs/<run_id>/
  config.resolved.json     # configuración resuelta (rutas absolutas)
  provenance.json          # commit git y estado (leídos sin modificar el repo), versiones, hashes, dispositivo, semillas
  metrics.jsonl            # una línea por época
  checkpoints/last.pt      # estado completo para reanudar
  checkpoints/best.pt      # mejor Dice macro por paciente de validación
```

`run_id` por defecto: `<AAAAMMDDTHHMMSSZ>-<8 hex del hash de la config>`; con `--run-id` (letras, dígitos, `.`, `_`,
`-`, máx. 64). **Un run existente nunca se sobrescribe** (código 2). Si falla la creación inicial (config, procedencia o
`metrics.jsonl`), la carpeta a medias se borra. Mientras `train`/`--resume` trabaja sobre un run, existe `.lock` (creado
con `O_EXCL`, contiene el PID): un segundo proceso falla con código 2; si un proceso murió sin liberarlo, hay que
borrarlo a mano tras comprobar que no hay otro activo. `provenance.json` incluye `git.commit` y `git.dirty`
(`git --no-optional-locks`; `dirty` solo mira archivos versionados y **ignora los no versionados**), Python, plataforma y versiones de torch/MONAI/numpy/scipy/nibabel/pydantic/cerberus, el
informe de `device`, semillas, límites de determinismo, `hashes` (`eligible_records_sha256`, `split_sha256`,
`weights_sha256`, `cache_key`, `config_sha256`), tamaños de train/val y el informe de transferencia.

`metrics.jsonl`: `epoch`, `step`, `train_loss`, `train_batches`, `lr`, `amp_skipped_steps`, `seconds` y, si se validó,
`val_dice`, `val_dice_per_patient`, `val_studies`, `val_patients`, `improved`, `best_val_dice`, `best_epoch`,
`epochs_without_improvement`. Las líneas con clave `event` no son épocas: `resume_override` (campos ampliados al
reanudar, con `from`/`to`), `best_orphaned` y `best_missing` (ver reanudación).

`last.pt` (leído con `weights_only=True`): `model`, `optimizer`, `scheduler` (`null`), `scaler` (AMP o `null`), `epoch`
(épocas completadas), `step`, `best_metric`, `best_epoch`, `early_stopping`, `finished`, `stop_reason`, `rng` (Python,
NumPy, PyTorch y CUDA), `config`, `compat`, `hashes`, `metrics_history` y `transfer`. `best.pt`: `model`, `epoch`,
`metric`, `threshold`, `config`, `compat`, `transfer`. Ambos se escriben de forma atómica (temporal en la misma carpeta,
`fsync`, `os.replace`, `fsync` de la carpeta): un fallo a mitad deja intacta la versión anterior y ningún archivo
parcial; permisos 0644. Orden al final de cada época: `best` (si mejoró) → `last` → línea de `metrics.jsonl`.

### Reanudación (`--resume`)

Se reanuda en límite de época dentro del mismo run; `--resume` debe ser `<work_dir>/runs/<id>/checkpoints/last.pt` de
la configuración dada. Se rechaza (código 7, nombrando cada diferencia) si cambia algo de la huella `compat`: tarea,
etiqueta, orden y número de canales, arquitectura y cabeza, `split_sha256`, `eligible_records_sha256`, clave de caché,
`weights_sha256` o la configuración relevante (el mensaje lista las claves cambiadas, p. ej. `training.learning_rate`).
Quedan fuera de la huella `paths`, `weights.path` (ya la fija `weights_sha256`) y los límites de recursos
(`preprocess.cache_enabled`, `cache_limit_gb`, `min_free_disk_gb`, `num_workers`), que pueden cambiar libremente.
`training.max_epochs` y `training.early_stopping_patience` pueden **subir** (nunca bajar): el cambio se registra como
evento `resume_override` en `metrics.jsonl` (y en el historial de `last.pt`), y un run terminado por ese motivo se
reabre. Cualquier otro cambio (`validate_every`, `learning_rate`, pérdida, parche, semillas…) se rechaza.

Se restauran red, optimizador, scaler, contadores, parada temprana y RNG, y `metrics.jsonl` se reescribe desde el
historial del checkpoint (descarta líneas de épocas posteriores a un corte). Coherencia de `best.pt`: como se escribe
antes que `last.pt`, un corte entre ambos deja un `best.pt` de una época que `last.pt` no registra; al reanudar se
aparta como `best.orphan-epoch<N>.pt` (no se borra), se registra `best_orphaned` y la repetición de la época lo
regenera si vuelve a mejorar (en CPU, idéntico; en CUDA puede no repetirse y entonces el `best.pt` vigente sale de la
siguiente mejora). Si el run ya había terminado y no se amplía nada, no hace nada y devuelve 0.

### Dry-run (`--dry-run`)

Valida configuración y límites de FT3, dispositivo, inventario y `splits.json`, **todas** las entradas de caché de
train/val (lectura completa con SHA-256), pesos (existencia, SHA-256, carga estricta, cabeza nueva, congelación) y
hace un forward sin gradiente de un parche (comprueba shape `[1, 1, *patch_size]` y valores finitos) y una predicción
por ventana deslizante del primer volumen de val (que puede ser mayor que el parche). Sin backward,
sin actualizar pesos (lo comprueba con un hash del `state_dict`), sin crear el run y sin descargar nada. Estima el disco
de los checkpoints (red ×4 en float32 + 10 %) frente al espacio libre y `min_free_disk_gb` (código 6 si no cabe).

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
  backend/tests/test_training_inventory.py backend/tests/test_training_splits.py \
  backend/tests/test_training_prepare.py backend/tests/test_training_train.py
```

Cubren el esquema, la CLI, la ausencia de imports de torch/MONAI/nibabel al arrancar (y de nibabel/numpy en `split`), el inventario sobre NIfTI
sintéticos (affines y spacings distintos, canal faltante, solo T2*, GTV ausente o vacía, 4D, affine singular,
spacing no positivo, archivos dañados, traversal, symlinks e identificadores inválidos) y la partición
(determinismo, agrupación por paciente, duplicados, mínimos e inmutabilidad). FT2 (`test_training_prepare.py`)
cubre, con fantomas definidos en coordenadas de mundo: orden de canales, geometría (spacing, permutación, flips y
oblicuo; imagen y GTV coinciden en espacio físico), GTV binaria tras NN, GTV no binaria/NaN/Inf, GTV vacía,
GTV fuera del soporte o perdida en el remuestreo (señales), remuestreo sin ceros dentro del casco y GTV en el plano de
borde (grid no centrado, spacing 0.9375, ejes invertidos), salida fija de `normalize_nonzero`,
desregistro/FOV/rotación, fuente modificada, registro manipulado, normalización, máscara cerebral frente a soporte no nulo, independencia
de la imagen respecto a la GTV, restauración ida y vuelta, parches pos/neg sembrados, augmentations deterministas,
caché (acierto, invalidación por configuración/versión/bibliotecas/tolerancia/fuente, byte alterado, hash de array,
escritura atómica con informe persistido, temporales huérfanos, límite, espacio libre simulado), preflight y la CLI
de extremo a extremo (incluido el código 4 sin elegibles). No usan red, `Data/001` ni GPU.

FT3 (`test_training_train.py`) usa una caché sintética de 16³ escrita con `StudyCache.store`, inventario y split reales,
una red pequeña inyectable (`ModelSpec`) y SegResNet real con pesos artificiales generados en el test: nombre y shapes
de `conv_final.2`, carga estricta, tensores transferidos idénticos, cabeza nueva determinista por semilla, SHA-256
incorrecto y pesos ausentes, llaves faltantes/sobrantes y shapes, backward que actualiza SegResNet real respetando la
congelación, `freeze_modules` inválido, NaN en la pérdida, CUDA pedida sin GPU, caché incompleta, artefactos y
procedencia, escritura atómica con fallo simulado, run existente, equivalencia bit a bit de la reanudación,
reanudación rechazada (split, canales, configuración, bajar `max_epochs`, `validate_every`), ampliación de
`max_epochs`/paciencia y cambios de recursos aceptados, recorte de `metrics.jsonl` al reanudar, corte entre `best` y
`last` seguido de reanudación, parada temprana con empates, `validate_every > 1`, gradiente NaN con pérdida finita,
predicción de validación NaN, pasos AMP saltados (scaler simulado), ventana final de acumulación corta frente a una
referencia manual, validación con GTV vacía, restauración del estado global (RNG y entorno), candado del run, limpieza
de un run a medias, dry-run sin cambios de pesos (con ventana deslizante) y la CLI de extremo a extremo. El forward de SegResNet con parche 96³ está marcado `slow`.
