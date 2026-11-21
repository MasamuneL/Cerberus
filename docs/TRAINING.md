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
| FT4 | `evaluate` (incluye `--baseline` y `--optimize-threshold`), `export` y `load_export` | implementado |
| FT5 | `smoke --synthetic` y manual de uso | implementado |

Funcionan `validate` y `device` (FT0), `inventory` y `split` (FT1), `prepare` y `preflight` (FT2), `train` (FT3),
`evaluate` y `export` (FT4) y `smoke --synthetic` (FT5). El trainer, la evaluación y la exportación solo se han
ejecutado con datos y pesos sintéticos en CPU (tests y `smoke`): **no se ha hecho ningún fine-tuning real ni existe un
modelo adaptado evaluado**, y no se ha medido ninguna duración ni consumo de recursos sobre el dataset real (las cifras
de `preflight` son estimaciones, no mediciones). Para el recorrido futuro con datos reales, vaya a
[«Manual de uso»](#manual-de-uso).

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | correcto |
| 1 | `device --require-cuda` o `train` con `training.device = "cuda"` sin CUDA disponible |
| 2 | uso incorrecto de argumentos o configuración inválida/ilegible |
| 3 | subcomando declarado pero no implementado (hoy ninguno: FT0–FT5 están implementados) |
| 4 | dataset/inventario inutilizable (raíz inexistente o ilegible, salida dentro del dataset, dos rutas de E/S que son el mismo archivo, inventario ilegible o manipulado), pocos pacientes, `splits.json` existente incompatible, o ningún estudio elegible en `prepare`/`preflight` |
| 5 | `prepare` terminó, pero al menos un estudio falló (los demás sí se prepararon; ver el informe) |
| 6 | recursos insuficientes: `prepare` se detiene por el límite de caché o el espacio libre; `preflight` estima que no cabe; `train` sin memoria (nunca reduce batch/parche) o `train --dry-run` sin disco para los checkpoints |
| 7 | `train`: pesos ausentes o con SHA-256 distinto, checkpoint incompatible (llaves faltantes/sobrantes, shapes), `freeze_modules` inválido o `--resume` rechazado; `evaluate`/`export`: hashes del run distintos de los datos actuales, checkpoint ausente o incompatible, pesos del baseline con SHA-256 distinto |
| 8 | `train`: fallo numérico (NaN/Inf en pérdida, gradientes o predicción de validación); `evaluate`: predicción con NaN/Inf o de forma incorrecta |
| 9 | `smoke --synthetic`: algún paso del recorrido sintético falló (el informe indica cuál) |

En `train`, el código 2 también cubre un `--run-id` inválido o ya existente (un run nunca se sobrescribe), un run en
uso por otro proceso (candado `.lock`) y límites de
FT3 (`preprocess.num_workers` distinto de 0 o caché desactivada); el 4, inventario/`splits.json`/caché inutilizables.

En `evaluate` y `export`: 2 = la carpeta de salida ya existe (nunca se sobrescribe), run en uso (`.lock`),
`--optimize-threshold` fuera de `--split val` (o con test ya evaluado, o `threshold.json` existente) u opciones
incompatibles; 4 = run incompleto o fuera de `<work_dir>/runs`, inventario/split/caché inutilizables, o un estudio no
evaluable (fuente con SHA-256 distinto del inventario, GTV no binaria, geometría incompatible o con cizalla, fallo
del pipeline original en el baseline: `EvaluationDataError` con su código); 2 también si falta `--checkpoint` con
`--split test` o `--bootstrap` < 100; 1 =
CUDA pedida sin GPU; 6 = sin memoria. En `smoke`, 2 = `--work-dir` dentro del repo o no vacío.

## Uso con el entorno normal (CPU)

El entorno de la app (`uv sync`) instala el paquete en modo editable y sirve para `--help`, validar
configuraciones y ejecutar los tests. No necesita red ni GPU y no importa torch ni MONAI al arrancar la CLI.

```bash
uv sync
uv run python -m cerberus_training --help
uv run python -m cerberus_training train --help
uv run python -m cerberus_training validate --config configs/training/gtv_binary.json
uv run python -m cerberus_training device
uv run python -m cerberus_training smoke --synthetic   # recorrido sintético completo (no es fine-tuning real)
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

## Evaluación (`evaluate`)

```bash
uv run python -m cerberus_training evaluate --run storage/training/runs/<run_id> --split val
uv run python -m cerberus_training evaluate --run storage/training/runs/<run_id> --split val --optimize-threshold
uv run python -m cerberus_training evaluate --run storage/training/runs/<run_id> --split test --checkpoint best
uv run python -m cerberus_training evaluate --run storage/training/runs/<run_id> --split test --baseline
# Opciones: --checkpoint {best,last} (obligatorio con --split test; best por defecto en val),
#           --bootstrap N (1000; mínimo 100), --bootstrap-seed S (42), --device {cpu,cuda} (sustituye training.device)
```

Es un comando **explícito**: `train` nunca evalúa test ni importa este módulo (lo comprueba un test). Código en
`backend/cerberus_training/evaluate.py`.

1. **Run y datos.** Lee `config.resolved.json` del run (que debe estar en `<work_dir>/runs/`), recalcula inventario,
   `splits.json` y clave de caché como `train`, y exige que los hashes de `provenance.json` (`eligible_records_sha256`,
   `split_sha256`, `weights_sha256`, `cache_key`, `config_sha256`) y la huella `compat` del checkpoint coincidan con
   los actuales (código 7 si no). Los estudios salen de `splits.json` → `partitions.<split>`. Mientras evalúa, toma
   el candado `.lock` del run.
2. **Checkpoint.** En val, `best.pt` por defecto; **con `--split test` hay que elegirlo explícitamente**
   (`--checkpoint best|last`, código 2 si falta), para que la elección no dependa de un valor por defecto. Carga
   estricta. Cada evaluación de test (también la del baseline) registra en `summary.json` →
   `prior_test_evaluations` las evaluaciones `evaluation/test*` que ya existían (carpeta y fecha) y, si hay alguna,
   añade un aviso en `warnings` que la CLI imprime como `AVISO`: repetir test y elegir entre resultados invalida la
   estimación.
3. **Umbral.** El guardado en `best.pt` (`training.threshold`, 0.5 por defecto; con `last`, el de la configuración).
   `--optimize-threshold` (**solo con `--split val`**) prueba los candidatos fijos 0.05, 0.10, …, 0.95 y elige el de
   mayor Dice macro por paciente en val, en el grid de referencia (empates: el más cercano al umbral del checkpoint y
   después el menor), evalúa val con él (aviso: métricas de val optimistas) y **solo si esa evaluación termina bien**
   lo guarda en `runs/<id>/threshold.json` (publicación exclusiva, una sola vez, ligado al `state_sha256` del
   checkpoint), justo antes de publicar la carpeta de val. Se rechaza si ya
   existe `threshold.json` o alguna evaluación `evaluation/test*`. Las evaluaciones posteriores (incluida test) usan
   `threshold.json` si corresponde al mismo checkpoint; si no, el umbral del checkpoint con un aviso. **Sobre test
   nunca se optimiza nada.**
4. **Predicción.** Ventana deslizante sobre el volumen preparado completo (`eval_sample`, ventana `patch_size`,
   solapamiento 0.5, sin augmentations, sigmoide) y `probabilidad > umbral`.
5. **Grid de comparación.** La máscara binaria se restaura con vecino más próximo al **grid original de la T1c**
   (`restore_to_reference`) y se compara con la **GTV original** del dataset (`transforms.reference_label`): se
   relee de `data_root` con identificadores revalidados, SHA-256 verificado contra el inventario, misma caja física
   que la T1c y valores {0, 1}; si ya está en el grid de la T1c se usa tal cual, si no (otro spacing, permutación o
   flips sobre la misma caja) se lleva a ese grid con vecino más próximo (`label_resampled = true`). La GTV nunca pasa
   por el recorte al soporte, así que los vóxeles perdidos en `prepare` (`label_lost_voxels`) cuentan como **falsos
   negativos**. El spacing de las métricas son las normas de columna del affine de la T1c; se exige que sus ejes sean
   ortogonales (un grid oblicuo rotado vale; con cizalla, código 4), porque HD95 usa una transformada de distancia
   con spacing por eje.
6. **Métricas por estudio** con `cerberus_api.segmentation.mask_metrics` (Dice portado de `cerberus_eda.py:178-181`):
   `dice` (= F1), `recall`, `precision`, `hd95_mm`, `volume_error_cm3` (predicción − GTV) y `abs_volume_error_cm3`.
   Ambos vacíos → Dice 1; HD95 null si alguna máscara está vacía; recall null sin GTV y precisión null sin predicción.
   `empty_case`: `both_empty`, `pred_empty` (solo la predicción vacía), `gtv_empty` (solo la GTV vacía) o `none`.
7. **Agregación.** Por paciente, media de sus tiempos sobre los valores no nulos (con su denominador `<métrica>_n`);
   entre pacientes: media, desviación estándar muestral (ddof = 1; null con un paciente), mediana, Q1/Q3 e IQR
   (percentiles con interpolación lineal), pacientes y estudios válidos, e **IC 95 % bootstrap percentil remuestreando
   pacientes** con reemplazo (`numpy.random.default_rng(--bootstrap-seed)`, `--bootstrap` réplicas, mínimo 100, las
   mismas para todas las métricas; en cada réplica se promedian los pacientes con valor no nulo y se descartan las
   réplicas sin ninguno; null con menos de 2 pacientes con valor o si no queda ninguna réplica válida).

### Salidas

```text
runs/<run_id>/evaluation/<split>/            # best
runs/<run_id>/evaluation/<split>-last/       # --checkpoint last
runs/<run_id>/evaluation/<split>-baseline/   # --baseline
  per_study.csv  per_patient.csv  summary.json
runs/<run_id>/threshold.json                 # solo con --optimize-threshold
```

**Nunca se sobrescribe**: si la carpeta existe, código 2 (no hay `--force`; para repetir, mueva o borre la carpeta a
conciencia). Los tres archivos se escriben en una carpeta temporal hermana que se renombra al final: un fallo no deja
una evaluación a medias.

- `per_study.csv`: `study_id, patient, timepoint, threshold, gtv_voxels, pred_voxels, gtv_cm3, pred_cm3, empty_case,
  dice, recall, precision, hd95_mm, volume_error_cm3, abs_volume_error_cm3, spacing_mm` (`x;y;z`), `label_resampled`,
  `label_lost_voxels` (+ `baseline_channels`, `baseline_warnings` en el baseline). Null = celda vacía.
- `per_patient.csv`: `patient, n_studies` y, por métrica, la media y `<métrica>_n`.
- `summary.json`: `schema_version`, `model` (`adapted`/`baseline`), `run_id`, `split`, `created_utc`, `hashes`,
  `checkpoint` (`kind`, `epoch`, `state_sha256`, métrica de selección), `threshold` (`value`, `source`:
  `checkpoint`/`optimized_on_val`/`baseline_fixed`), `inference` (predictor, ventana, solapamiento, `amp` realmente
  usado, `TRANSFORMS_VERSION`, canales), `prior_test_evaluations` (solo en test), `comparison_grid`, `aggregation`, `empty_rules`,
  `bootstrap`, `n_studies`, `n_patients`, `metrics.<métrica>` (`n_valid_patients`, `n_patients`, `n_valid_studies`,
  `n_studies`, `mean`, `std`, `median`, `q1`, `q3`, `iqr`, `ci95`), `empty_cases` y `warnings`, más versiones.

### Baseline (`--baseline`)

Evalúa la salida **TC** del modelo original de 3 salidas con **su propio pipeline**: `cerberus_api.segmentation.
segment_regions` (la misma función que usa `run_segmentation` en la API, extraída sin cambiar su comportamiento):
canales de `CHANNEL_MAP`, `resample_to_output` a 1 mm sobre la T1c, imágenes × brain_mask, `normalize_nonzero`,
ventana deslizante 240×240×160 con solapamiento 0.5 (`segresnet_predictor`), TC = canal 0 > 0.5 recortado a la
brain_mask. Recibe los archivos seleccionados en el inventario (SHA-256 verificado) y la TC se lleva al grid
original de la T1c con vecino más próximo, donde se compara con la GTV original igual que el modelo adaptado. La
geometría de referencia se lee solo del `meta` de la entrada de caché (`StudyCache.load_geometry`, con clave y fuentes
verificadas; no carga el volumen). Un fallo del pipeline original (nibabel, forma de la salida…) es un error de datos
del estudio con código `baseline_failed` (código de salida 4). Sin
predictor inyectado usa los pesos de `weights.path` verificados con `weights.sha256` (**nunca descarga**).

Es una **referencia imperfecta**: TC (tumor core de BraTS) no es GTV y las cifras no son una equivalencia de etiquetas.
`summary.json` lo dice en `label_caveat` y `warnings`, y registra en `baseline` el bundle, el SHA-256 de los pesos, la
salida usada, `CHANNEL_MAP` y el preprocesamiento, y en `differences_vs_adapted` las diferencias con el modelo
adaptado (etiqueta, umbral, grid y recorte, máscara cerebral sobre la predicción, ROI de la ventana, política de
canales y pesos). No admite `--optimize-threshold` ni `--checkpoint`.

## Exportación (`export`)

```bash
uv run python -m cerberus_training export --run storage/training/runs/<run_id> [--checkpoint last]
```

Verifica el run y el checkpoint igual que `evaluate` (solo runs de SegResNet) y escribe, sin sobrescribir nunca
(código 2 si existe):

```text
runs/<run_id>/export/          # best (export-last/ con --checkpoint last)
  model.pt        # state_dict de SegResNet de 1 salida (solo tensores; se carga con weights_only=True)
  export.json     # manifiesto
  model_card.md   # ficha del modelo en español
```

`export.json`: `architecture` (`monai.SegResNet`, sus `kwargs`, `out_channels = 1`, cabeza `conv_final.2`),
`channel_order` y `channels`, `transforms` (`TRANSFORMS_VERSION`, spacing, orientación, política de máscara, pasos,
ventana deslizante y restauración), `threshold` (valor y origen, como en `evaluate`), `checkpoint`, `hashes`
(`weights_file_sha256` de `model.pt`, `state_sha256` del state_dict, `pretrained_weights_sha256`, `split_sha256`,
`eligible_records_sha256`, `cache_key`, `config_sha256`), `dataset` (CFB-GBM, TCIA, DOI `10.7937/v9pn-2f72`),
`license` (CC BY 4.0), `citation`, `pretrained`, `pretraining_overlap` y `evaluation`. `transforms.inference`
registra la ventana, el solapamiento y `amp_training` (AMP solo actúa en CUDA). **Sin puntuaciones ficticias:**
`evaluation.status` es `not_evaluated` si no hay ninguna evaluación de ese mismo checkpoint (mismo `state_sha256`);
si la hay, `evaluated_val` (solo val: cifras optimistas, falta test) o `evaluated_test` (hay test), con
`splits_evaluated`, y cada resumen se cita con su partición, fecha (`created_utc`), ruta y métricas; la frase de la
ficha depende del estado.

`pretrained` registra los pesos iniciales: nombre/versión del bundle de la configuración y su SHA-256 y, si los pesos
siguen la estructura `<bundle>/models/model.pt`, los campos `name`, `version`, `authors`, `copyright`, `data_source`,
`intended_use` y `references` de `<bundle>/configs/metadata.json` (verificado en el bundle local 0.5.4; ese archivo
**no** tiene campo de licencia), la licencia reconocida en `<bundle>/LICENSE` (Apache 2.0) y la citación tomada de
`references`. Lo que no se puede leer se marca `"no verificado"`; `version_matches_config` indica si la versión del
metadata coincide con `weights.bundle_version`. Las
evaluaciones del baseline se citan aparte como referencia imperfecta. La ficha menciona la métrica de selección de
`best` (Dice macro por paciente de val del entrenamiento) dejando claro que no es una evaluación.

`cerberus_training.export.load_export(directorio, expected=None)` reconstruye SegResNet desde `export.json` (exige que
sus `kwargs` sean exactamente `SEGRESNET_KWARGS`), comprueba el SHA-256 de `model.pt`, carga con correspondencia estricta y comprueba el SHA-256 del state_dict; `expected`
(p. ej. `{"split_sha256": …, "cache_key": …}`) se contrasta con los hashes del manifiesto. Cualquier discrepancia es
`ExportError`. Devuelve el modelo en modo `eval`, el manifiesto, el umbral y el orden de canales. La integración del
modelo exportado en la API/UI queda fuera de alcance (otro ticket).

## Smoke sintético (`smoke --synthetic`)

```bash
uv run python -m cerberus_training smoke --synthetic [--work-dir DIR_NUEVA_O_VACIA] [--keep] [--verbose]
```

**SINTÉTICO — NO ES FINE-TUNING REAL.** Comprueba el cableado de extremo a extremo con datos y pesos artificiales, en
CPU, sin red y sin el dataset. Sus Dice, pérdidas y exportaciones no tienen ningún valor clínico ni científico y **no
sustituyen** la auditoría del dataset real ni el piloto en GPU. Código en `backend/cerberus_training/smoke.py`.

Qué genera (todo en un directorio temporal, fuera del repo y de cualquier `data_root`):

- NIfTI diminutos (32³, 1 mm) con la convención `cerberus_v1`: 7 pacientes y 11 estudios con varios tiempos
  (`001` t0/t1, `002` t0/t1/t2, `006` t0/t1…), un paciente con el eje x invertido (otra orientación de vóxeles), un estudio
  **excluido por canal faltante** (`007/t0` sin FLAIR → `missing_channel`), otro **excluido por GTV ausente**
  (`002/t2` → `missing_label`) y una GTV **vacía** (`006/t1`) que debe aparecer como señal de revisión `empty_label`.
  El inventario debe dar exactamente 9 elegibles, esas dos exclusiones y esa señal; si no, el paso falla.
- Un checkpoint artificial de **SegResNet real de 3 salidas** (pesos aleatorios con semilla) con su SHA-256, y una
  configuración derivada: CPU, sin AMP, parche 16³ (múltiplo de 8), `grad_accum_steps` 8 (una sola ventana por época
  = 1 paso de optimización) y `max_epochs` 2.

Se usa la SegResNet real y no la red pequeña inyectable de los tests porque a este tamaño cada paso cuesta fracciones de
segundo y así el smoke ejercita la transferencia real (`conv_final.2`), la ventana deslizante y `load_export`.

Pasos (cada uno llama a `main([...])`, es decir, a las mismas funciones que la CLI) y qué comprueba cada uno:

| # | Paso | Comprobación |
|---|---|---|
| 1 | datos y pesos sintéticos | se escriben datos, pesos, configuración y el marcador `SINTETICO_NO_ES_FINE_TUNING.txt` |
| 2 | `validate` | la configuración derivada es válida |
| 3 | `inventory` | 9 elegibles de 11; exclusiones `missing_channel` y `missing_label`; señal `empty_label` |
| 4 | `split` | train/val/test no vacíos y sin pacientes compartidos |
| 5 | `preflight` | código 0 (recursos y pesos) |
| 6 | `prepare` | todos los elegibles en caché, sin errores |
| 7 | `train --dry-run` | código 0 y **no se crea ningún run** |
| 8 | `train` (2 pasos) | `step == 2`, `epoch == 2`, pérdida finita, los pesos cambian respecto al checkpoint inicial, existe `best.pt` |
| 9 | reanudación | se corta tras la 1.ª época (`run_training(stop_after_epochs=1)`, opción que la CLI no expone) y se reanuda con `train --resume`: los pesos y el estado del optimizador de `last.pt`, los pesos de `best.pt` y `metrics.jsonl` son idénticos a los de la ejecución continua |
| 10 | `evaluate val` | resumen con estudios y pacientes (bootstrap 100) |
| 11 | `evaluate test --checkpoint best` | idem, en test (nunca se optimiza nada sobre test) |
| 12 | `export` | `model.pt`, `export.json`, `model_card.md` y estado `evaluated_test` |
| 13 | `load_export` | el modelo recargado es idéntico a `best.pt`, con los hashes de split y caché verificados |

Salida: banner sintético, una línea por paso con ✓/✗, duración, resultado y rutas (con `--verbose` también la salida de
cada subcomando; si un paso falla, la salida de ese paso siempre se muestra y el resto se marca como omitido). Código de
salida **0 solo si pasan los 13 pasos**; 9 si alguno falla; 2 si `--work-dir` está dentro del repo o no está vacío (el
smoke nunca pisa archivos ajenos). Durante el recorrido se **bloquea la red** parcheando `socket.socket.connect` y `connect_ex`
(familias IPv4/IPv6), `socket.getaddrinfo` y `socket.create_connection`: un intento lanza `OSError`, se cuenta y hace
fallar el smoke (código 9) aunque el código que lo intentó capture el error. No intercepta otras vías (UDP con `sendto`
sin `connect`, sockets abiertos antes, subprocesos): es una red de seguridad, no un aislamiento del sistema operativo.

El directorio temporal se borra al terminar salvo con `--keep`; con `--work-dir` se conserva siempre (no se borra un
directorio elegido por la persona usuaria). Al conservarlo se escriben `smoke_report.json` (`synthetic: true`,
`real_finetuning: false`, pasos, hechos y duración) y el marcador `SINTETICO_NO_ES_FINE_TUNING.txt` en el directorio y
en cada run; los runs se llaman `smoke-sintetico-continuo` y `smoke-sintetico-interrumpido`.

Corre en CPU en unos segundos (la duración depende de la máquina y no se garantiza). La prueba `backend/tests/test_training_smoke.py` lo ejecuta entero vía `main([...])`, comprueba el
código 0, que no hay intentos de red, que el temporal se borra y que no cambia `git status`, `storage/` ni `models/`.

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

## Manual de uso

> **Nada de lo que describe este manual se ha ejecutado todavía sobre el dataset real.** Es el recorrido previsto para
> cuando se disponga del dataset completo y de una GPU. Hasta hoy solo se ha ejecutado `smoke --synthetic` y los tests,
> con datos y pesos artificiales en CPU. No hay duraciones ni consumos medidos con CFB-GBM: `preflight` los estima,
> pero son estimaciones. Quedan pendientes la auditoría del dataset completo, el piloto en GPU, el entrenamiento,
> la validación científica y la integración del modelo en la API/UI ([plan §10](PLAN_PIPELINE_FINETUNING.md)).

Atajo usado abajo: `CT` = `uv run --project training-env python -m cerberus_training` (entorno CUDA independiente,
véase [«Entorno CUDA independiente»](#entorno-cuda-independiente-training-env)). En una máquina sin GPU, `uv run python -m
cerberus_training` sirve para todo salvo entrenar en CUDA.

### 0. Antes de empezar

1. Dataset CFB-GBM descargado de TCIA (CC BY 4.0, DOI `10.7937/v9pn-2f72`) en un directorio **externo al repo** con la
   convención `cerberus_v1` (`<paciente>/<tiempo>/<int(paciente)>_<tiempo>_<secuencia>.nii.gz`). Si la descarga usa otra
   estructura, hace falta un adaptador (véase «Inventario»).
2. Pesos iniciales locales del bundle `brats_mri_segmentation` (versión del plan: 0.5.4) y su SHA-256
   (`shasum -a 256 .../model.pt`). `train` nunca descarga nada.
3. Entorno: `uv sync --project training-env --locked` y `CT device --require-cuda` (código 1 si no hay GPU). Revise los
   `AVISO` de arquitectura de GPU.
4. **Compruebe primero el cableado:** `uv run python -m cerberus_training smoke --synthetic` debe terminar con código 0.
5. Copie `configs/training/gtv_binary.json` a un archivo local (p. ej. `storage/training/gtv_binary.local.json`; `storage/`
   está ignorado por Git) y edite `paths.data_root`, `paths.work_dir`, `weights.path` y `weights.sha256`
   (el marcador de 64 ceros del ejemplo se rechaza). No hay que tocar nada más para un primer intento: los
   hiperparámetros son un punto de partida, no un óptimo validado. Valide: `CT validate --config <config>`.

Usaremos `CFG=<config>` abajo. Cada paso imprime un informe en español; revise **todos** antes de pasar al siguiente.

### 1. Inventario

```bash
CT inventory --config $CFG --summary storage/training/inventory_summary.json
```

Qué revisar (el resumen impreso y `inventory_summary.json`):

- **Elegibles frente a excluidos** y el **recuento de exclusiones por motivo** (`missing_channel`, `missing_label`,
  `not_3d`, `invalid_affine`, `invalid_spacing`, `unreadable`…). Compare con lo esperado de TCIA (264 sujetos; no todos
  los estudios tendrán las 4 secuencias + GTV). Con muchos `missing_channel`, **no relaje el perfil en silencio**: un
  perfil de compatibilidad sería otro experimento declarado (plan §4.3).
- **Señales de revisión** (no excluyen): `empty_label` (GTV vacía: se conserva), `invalid_brain_mask` (se ignora),
  `duplicate_within_study`. Anote cuántas hay y decida si alguna requiere mirar el caso.
- **Duplicados exactos entre estudios** (los pacientes con canales idénticos caerán en la misma partición) y carpetas
  **rechazadas** (`invalid_identifier`, que se muestran solo por `name_sha8`).
- **Estratos** t0/seguimiento y **secuencia elegida por canal** (cuántos estudios usan `t1eg` frente a `t1tse` para T1).
- La cohorte **no puede depender de resultados de prueba**: toda regla de exclusión se fija y se anota antes de entrenar.

### 2. Partición

```bash
CT split --config $CFG
```

Revise: pacientes por partición (70/15/15 por paciente, semilla 42), los `AVISO` de desviación por duplicados fusionados,
`pretraining_overlap` (queda `unknown`: **no** lo cambie a `verified` sin hacer de verdad la revisión de solapamiento con
el preentrenamiento del bundle) y que ninguna partición esté vacía. `splits.json` es inmutable; si después cambia el
inventario o la configuración, `split` y `train` fallan con código 4 en lugar de redistribuir.

### 3. Preflight

```bash
CT preflight --config $CFG
```

Revise: disco de caché estimado (cota superior) frente a `cache_limit_gb` y al espacio libre más `min_free_disk_gb`, RAM
aproximada de `prepare` y de un lote, estado de los pesos (existencia y SHA-256). Código 6 si no cabe. Son **estimaciones
sin medir** sobre el dataset real; la RAM del lote **no incluye activaciones ni gradientes** de la red.

### 4. Preparación

```bash
CT prepare --config $CFG
```

Revise `prepare_report.json` y el informe impreso (se escribe siempre, también si se aborta):

- **Errores por estudio** y su código: `geometry_mismatch` (canal, GTV o máscara que no ocupa el mismo espacio físico que
  la T1c; **el remuestreo no corrige desregistro**), `non_binary_label`, `non_finite`, `source_changed`,
  `empty_brain_mask`… Código 5 si hay alguno.
- **Señales de revisión** de `review_totals`: `label_outside_support`, `label_vanished`, `label_outside_brain_mask`
  (cuenta de estudios y de vóxeles de GTV implicados), `no_brain_mask`, `empty_label`. La GTV nunca excluye un estudio por
  su posición, pero esos vóxeles cuentan como falsos negativos en la evaluación.
- **Un estudio elegible que falla en `prepare` deja la caché incompleta y `train` lo rechaza (código 4).** Hoy no hay un
  mecanismo de exclusión manual: no edite `inventory.jsonl` (cambiaría `eligible_records_sha256` y el split se
  rechazaría). Si ocurre, decisión pendiente: fijar y anotar una regla de calidad previa al entrenamiento y regenerar
  inventario y split en un `work_dir` nuevo, o registrar el caso para registro de imagen aparte.

### 5. Dry-run

```bash
CT train --config $CFG --dry-run
```

Valida todo sin backward ni actualizar pesos: entradas de caché de train/val (con SHA-256), pesos (SHA-256, carga
estricta, cabeza nueva `conv_final.2`), forward de un parche, ventana deslizante sobre un volumen de val, y disco para los
checkpoints. Revise los parámetros transferidos/nuevos, `output_shape`, los límites de determinismo (en CUDA no hay
reproducibilidad bit a bit) y que diga «Dry-run correcto». Con `training.device = "cuda"` y sin GPU, código 1.

### 6. Entrenamiento (solo en una ejecución futura solicitada)

```bash
CT train --config $CFG --run-id <nombre>
```

Revise `runs/<id>/metrics.jsonl` (pérdida finita y decreciente, `val_dice`, `epochs_without_improvement`,
`amp_skipped_steps`), `provenance.json` (commit, hashes, versiones) y que `best.pt` y `last.pt` existan. No elija
hiperparámetros ni umbrales mirando test. Si se interrumpe: `CT train --config $CFG --resume storage/training/runs/<id>/checkpoints/last.pt`
(solo con la misma configuración; solo se pueden **subir** `max_epochs` y `early_stopping_patience`).

### 7. Evaluación

```bash
CT evaluate --run storage/training/runs/<id> --split val                    # opcional: --optimize-threshold (solo val)
CT evaluate --run storage/training/runs/<id> --split test --checkpoint best # una sola vez, decidido de antemano
CT evaluate --run storage/training/runs/<id> --split test --baseline        # referencia imperfecta (TC ≠ GTV)
```

Revise `summary.json`: denominadores válidos por métrica, intervalos bootstrap por paciente, casos vacíos por separado,
`warnings` y `prior_test_evaluations` (repetir test y elegir entre resultados invalida la estimación). Fije antes de usar
test el mínimo de mejora que justificaría declarar éxito del experimento.

### 8. Exportación

```bash
CT export --run storage/training/runs/<id>
```

Revise `export.json` y `model_card.md`: `evaluation.status` (`not_evaluated`, `evaluated_val` o `evaluated_test`),
`pretraining_overlap`, licencia y citación del dataset. `load_export(directorio)` reconstruye el modelo verificando
hashes. El modelo exportado es un artefacto experimental independiente: no sustituye al modelo activo de Cerberus.

### Fallos frecuentes

| Síntoma | Código | Qué hacer |
|---|---|---|
| `device --require-cuda` o `train` con `training.device = "cuda"` sin GPU | 1 | Ejecute `CT device`; revise controlador e índice CUDA (RTX 50xx: pruebe otro índice y regenere el lock). No se degrada a CPU |
| Configuración inválida (clave desconocida, split que no suma 1, parche no múltiplo de 8, SHA-256 mal formado), `--run-id` ya existente o run con `.lock` | 2 | Lea el mensaje y corrija el JSON; use otro `--run-id` o `--resume`; borre `.lock` solo tras comprobar que no hay otro proceso |
| `evaluate`/`export` con la carpeta de salida ya existente; test sin `--checkpoint`; `--optimize-threshold` fuera de val | 2 | Nunca se sobrescribe: mueva o borre la carpeta a conciencia; pase `--checkpoint best\|last` explícito |
| Raíz del dataset ilegible, salida dentro del dataset, menos de 3 pacientes elegibles, `splits.json` incompatible con el inventario actual, caché incompleta en `train` | 4 | Revise el inventario; no se redistribuye un split: restaure el inventario original o use un `work_dir` nuevo; ejecute `prepare` |
| `prepare` con estudios fallidos (`geometry_mismatch`, `non_binary_label`, `source_changed`…) | 5 | Lea `prepare_report.json`; `source_changed` exige repetir `inventory`; el desregistro requiere registro aparte (véase paso 4: sin exclusión manual hoy) |
| `preflight`/`prepare` sin disco o sobre `cache_limit_gb`; `train` sin memoria | 6 | Libere disco o suba `cache_limit_gb`/`min_free_disk_gb` a conciencia; ante OOM ajuste `patch_size`/`batch_size` manualmente (nunca se reducen solos) y empiece un run nuevo: cambiar el parche invalida `--resume` |
| Pesos ausentes o con SHA-256 distinto, checkpoint incompatible, `--resume` rechazado (cambió split, canales o configuración), hashes del run distintos de los datos actuales | 7 | Compruebe `weights.path` y recalcule `shasum -a 256`; el mensaje lista las diferencias; no edite `provenance.json` ni los checkpoints |
| NaN/Inf en pérdida, gradientes o predicción | 8 | Revise datos y `learning_rate`; reanude desde el último `last.pt` válido o empiece un run nuevo |
| `smoke --synthetic` falla | 9 | Lea el paso ✗ y su salida; es un fallo del cableado, no de los datos reales: arréglelo antes de tocar el dataset |

### Recursos

- **Disco:** el dataset completo publicado en TCIA ocupa 208.01 GB (comprimido, solo lectura, fuera del repo); la caché
  de `prepare` vive en `<work_dir>/cache/` y `preflight` estima su tamaño descomprimido; los checkpoints se estiman en
  `--dry-run` (red ×4 en float32 + 10 %). `work_dir` y `data_root` deben ser disjuntos.
- **RAM:** `prepare` carga un estudio por vez y el trainer lee la caché de uno en uno (`num_workers = 0`); `preflight`
  da una cota aproximada. No se ha medido el consumo real con CFB-GBM, y el de la red (activaciones y gradientes) depende
  de `patch_size`, `batch_size` y la GPU: se medirá en el piloto.
- **Cómputo y tiempo:** sin cifras. Duración de `inventory` (lee todos los bytes de los archivos seleccionados para el
  SHA-256), de `prepare` y de cada época del entrenamiento: **sin medir**, se conocerán en el piloto.

### Qué queda pendiente

Según el [plan §10](PLAN_PIPELINE_FINETUNING.md), la implementación del pipeline está completa, pero **no se ha hecho**:

1. La auditoría del dataset completo (inventario real, exclusiones, estratos, duplicados, revisión de solapamiento con el
   preentrenamiento).
2. El piloto en GPU (instalación del entorno `training-env` en una máquina con CUDA, tamaño de parche y hardware
   necesarios, mediciones de tiempo y memoria).
3. El entrenamiento real.
4. La validación científica (mínimo de mejora fijado antes de usar test, evaluación única de test, interpretación).
5. La integración del modelo adaptado en la API/UI (otro ticket; exigiría actualizar los contratos de `PLAN_MVP.md`).

## Tests

```bash
uv run pytest -q backend/tests/test_training_config.py backend/tests/test_training_cli.py \
  backend/tests/test_training_inventory.py backend/tests/test_training_splits.py \
  backend/tests/test_training_prepare.py backend/tests/test_training_train.py \
  backend/tests/test_training_evaluate.py backend/tests/test_training_smoke.py
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

FT4 (`test_training_evaluate.py`) cubre métricas calculadas a mano con spacing anisotrópico (cubo desplazado: Dice
0.75 y HD95 2 mm; sobre-segmentación: Dice 128/144, precisión 0.8 y ±0.016 cm³), los tres casos vacíos, la agregación
tiempos → paciente con números a mano (media, desviación, cuartiles y denominadores), el bootstrap (determinista por
semilla, igual a una referencia manual por índices de paciente e invariante a repetir estudios de un paciente), la
restauración al grid de la T1c con flips, permutación anisotrópica y oblicuo frente a la GTV original, la GTV en otro
grid, la GTV perdida fuera del soporte contada como FN, el rechazo de cizalla, el aislamiento de test (el trainer no
importa la evaluación; optimizar el umbral en test o tras ver test es imposible; test usa el umbral persistido de
val; optimización no trivial con ruido de falsos positivos hasta 0.7 → umbral 0.70; `threshold.json` solo tras una
evaluación de val correcta; umbral de otro checkpoint ignorado con aviso; `--checkpoint` obligatorio en test y
`prior_test_evaluations`), el bootstrap con 2 de 50 pacientes válidos, la no sobrescritura, el candado y los hashes del run, una fuente modificada, el baseline con predictor falso
(canales y diferencias registradas) y, con SegResNet real de pesos artificiales sobre un workspace sintético
completo (NIfTI → inventario → split → prepare → train), la exportación de ida y vuelta (mismas salidas que
`best.pt`), `pretrained` con metadata sintética, `not_evaluated`/`evaluated_val`/`evaluated_test`, hashes y `kwargs`
alterados y la CLI de extremo a extremo. Un test `slow` recorre la ruta real de `evaluate_baseline` (pesos
artificiales de 3 salidas, `segresnet_predictor` con ROI 240×240×160 en CPU).

FT5 (`test_training_smoke.py`) ejecuta el recorrido completo de `smoke --synthetic` vía `main([...])` (13 pasos, SegResNet
real, unos segundos en CPU, sin `slow`): código 0, temporal borrado, `--work-dir` con informe y marcadores, red
bloqueada sin intentos (y un intento durante un paso hace fallar el smoke con código 9), temporal borrado también
ante `KeyboardInterrupt`, camino `PENDING` (código 3) ejercitado parcheando `PENDING`, `git status`/`storage/`/`models/` intactos, rechazo de `--work-dir` dentro del repo o no vacío,
fallo de un paso (código 9, resto omitido) y restauración del bloqueo de red.

## Estado y pasos futuros

Resumen verificado el 2026-11-21 sobre el estado real del pipeline de fine-tuning, la auditoría de los datos disponibles en el repositorio y la ruta pendiente hasta una eventual evaluación científica e integración.

### 1. Estado actual

- El pipeline **FT0–FT5** está implementado en `backend/cerberus_training/` (CLI `cerberus_training`, esquema estricto `configs/training/gtv_binary.json` y entorno CUDA independiente `training-env/`).
- Hasta la fecha **solo se ha ejecutado con datos y pesos sintéticos en CPU** mediante los tests automatizados y `uv run python -m cerberus_training smoke --synthetic` (13 pasos con red bloqueada y artefactos marcados `real_finetuning: false`; véase [`PROGRESS.md`](PROGRESS.md) `CP-058`).
- **No existe ningún entrenamiento real sobre CFB-GBM, ninguna ejecución en GPU CUDA ni ninguna validación científica** del modelo adaptado.

### 2. Inventario real sobre `Data/`

Salida obtenida el 2026-11-21 ejecutando el inventario de FT1 sobre la muestra local del repositorio (`/Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus/Data`):

```bash
uv run python -m cerberus_training inventory \
  --data-root /Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus/Data \
  --output /tmp/inventory.jsonl \
  --summary /tmp/inventory_summary.json
```

Salida resumida de la CLI:

```text
Estudios: 8 (1 elegibles, 7 excluidos); pacientes: 5 (1 con algún estudio elegible)
  exclusión missing_channel: 7 estudio(s) — falta un canal obligatorio del perfil estricto
  estrato baseline: {'eligible': 1, 'excluded': 4}
  estrato follow_up: {'excluded': 3}
  canal T1c (elegibles): {'t1gd': 1}
  canal T1 (elegibles): {'t1eg': 1}
  canal T2 (elegibles): {'t2tse': 1}
  canal FLAIR (elegibles): {'flair': 1}
Por paciente:
  001: t0 excluido (missing_channel)
  002: t0 excluido (missing_channel)
  003: t0 excluido (missing_channel); t1 excluido (missing_channel)
  004: t0 ok
  005: t0 excluido (missing_channel); t1 excluido (missing_channel); t2 excluido (missing_channel)
```

Desglose por estudio según el manifiesto `inventory.jsonl` generado por el comando:

| Estudio | Estrato | Elegible | Canales faltantes / motivo (`missing_channel`) |
|---|---|---|---|
| `001/t0` | `baseline` | No | Falta `T2` (`t2tse`; tiene `t2star`, no aceptado por el perfil estricto) |
| `002/t0` | `baseline` | No | Faltan `T1` (`t1eg`/`t1tse`) y `FLAIR` (`flair`); sí tiene `t2tse` |
| `003/t0` | `baseline` | No | Falta `T1` (`t1eg`/`t1tse`); sí tiene `t2tse` |
| `003/t1` | `follow_up` | No | Falta `T2` (`t2tse`; tiene `t2star`) |
| `004/t0` | `baseline` | **Sí** | Completo (`t1gd`, `t1eg`, `t2tse`, `flair` y `gtv`) |
| `005/t0` | `baseline` | No | Falta `T2` (`t2tse`; tiene `t2star`) |
| `005/t1` | `follow_up` | No | Falta `T2` (`t2tse`; tiene `t2star`) |
| `005/t2` | `follow_up` | No | Falta `T2` (`t2tse`; tiene `t2star`) |

- Con el perfil estricto (`configs/training/gtv_binary.json`), **solo 1 de 8 estudios (12.5 %) y 1 de 5 pacientes (`004/t0`) son elegibles**, insuficiente incluso para ejecutar `split` (exige al menos 3 pacientes elegibles).
- De los 7 excluidos, **5** fallan únicamente por ausencia de `t2tse` (cuentan con `t2star`, que la política `t2star_policy: "disabled"` no sustituye) y **2** (`002/t0`, `003/t0`) fallan por ausencia de `T1` y/o `FLAIR`.
- En la colección completa de TCIA (`https://www.cancerimagingarchive.net/collection/cfb-gbm/`, Tabla 3, consultada el 2026-11-21), `T2` (`t2tse`) figura solo en **125** (`T0`) + **15** (`T1`) + **11** (`T2`) = **151** estudios (frente a `T1Gd`: 264 + 163 + 118 = 545, o `T2*`: 241 + 136 + 94 = 471), por lo que la escasez de `t2tse` se reproducirá al descargar todo CFB-GBM. Cualquier relajación hacia un perfil de compatibilidad deberá declararse como experimento aparte ([`PLAN_PIPELINE_FINETUNING.md`](PLAN_PIPELINE_FINETUNING.md) §4.3).

### 3. Almacenamiento y caché de preprocesado

Medición por estudio local con `du -sh` (y `du -sk` para precisión en KiB) sobre `/Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus/Data/*/*`:

| Estudio | `du -sh` | `du -sk` (KiB) | Notas |
|---|---|---|---|
| `001/t0` | `772M` | `790348` | Incluye `ct` y `rtdose` |
| `002/t0` | `623M` | `637632` | Incluye `ct` y `rtdose` |
| `003/t0` | `507M` | `519268` | Incluye `ct` y `rtdose` |
| `003/t1` | `217M` | `221852` | Seguimiento sin `ct`/`rtdose` |
| `004/t0` | `759M` | `776828` | Incluye `ct` y `rtdose` |
| `005/t0` | `468M` | `479064` | Incluye `ct` y `rtdose` |
| `005/t1` | `255M` | `261380` | Seguimiento sin `ct`/`rtdose` |
| `005/t2` | `225M` | `229896` | Seguimiento sin `ct`/`rtdose` |
| **Total / media (8)** | **3 826 MiB / 478.25 MiB** | **3 916 268 / 489 533.5 KiB** | Media exacta: **478.06 MiB (~0.47 GiB)** |

- **Total de estudios en TCIA:** **sin verificar**. En la ficha oficial de la colección ([`https://www.cancerimagingarchive.net/collection/cfb-gbm/`](https://www.cancerimagingarchive.net/collection/cfb-gbm/), versión 4, consultada el 2026-11-21), la columna *Studies* de la tabla *Data Access* aparece vacía; la ficha publica **264 sujetos**, **3 981 imágenes** NIfTI y **208.01 GB** en total, además de la Tabla 3 por modalidad y tiempo (`T1Gd`/`MASK`: 264 + 163 + 118 = 545; `GTV`: 261 + 160 + 122 = 543; `T2`: 125 + 15 + 11 = 151). Al no publicarse la cifra total de estudios, la multiplicación `tamaño medio × total de estudios` queda **sin verificar** (a modo de referencia, 545 × 0.47 GiB ≈ 254 GiB, superior a los 208.01 GB publicados porque 5 de los 8 estudios locales son `t0` con `ct`/`rtdose`, más pesados que `t1`/`t2`).
- **Caché de preprocesado (`preflight`):** ejecutando `uv run python -m cerberus_training preflight` sobre el inventario real (`004/t0` elegible, grid destino `258×258×208` vóxeles, fórmula `18 B/vóxel + 64 KiB` de [`backend/cerberus_training/preflight.py`](../backend/cerberus_training/preflight.py)):
  - Cota superior sin recorte por estudio: **0.23 GB** (`249 281 152 B ≈ 0.232 GiB`), **1.11 GB** de RAM pico en `prepare` y **0.28 GB** de RAM de datos por lote (sin activaciones ni gradientes).
  - Extrapolando los `249 281 152 B` (`~0.232 GiB`) de `004/t0` en dos escenarios hipotéticos donde todos los estudios tuvieran ese mismo tamaño de grid destino (sin recorte al soporte cerebral): con **151 estudios** con `t2tse` en la Tabla 3 de TCIA la caché alcanzaría hasta **~35.06 GiB**, y en un eventual experimento futuro de compatibilidad con **545 estudios** (`T1Gd`/`MASK`) alcanzaría hasta **~126.53 GiB**. El consumo real puede ser menor al recortar al soporte cerebral o variar según la geometría de cada estudio; la decisión de ampliar `preprocess.cache_limit_gb` (`20.0` GiB por defecto en `configs/training/gtv_binary.json`) debe tomarse tras ejecutar `preflight` sobre el `inventory.jsonl` real de la cohorte completa.

### 4. Pasos futuros en orden

Todos los subcomandos indicados fueron verificados en la CLI actual (`--help`). Se asume una configuración local fuera de Git (p. ej. `CFG="$WORK_DIR/gtv_binary.local.json"`, copiada de `configs/training/gtv_binary.json` con `paths.data_root`, `paths.work_dir`, `weights.path`, `weights.sha256` real obtenido con `shasum -a 256` y `preprocess.cache_limit_gb` ajustado tras `preflight`).

1. **Descarga externa de CFB-GBM y comprobación inicial:**
   - En la ficha oficial de TCIA ([`https://www.cancerimagingarchive.net/collection/cfb-gbm/`](https://www.cancerimagingarchive.net/collection/cfb-gbm/), DOI `10.7937/v9pn-2f72`, CC BY 4.0, `208.01 GB`), sección *Data Access*, pulsar **`Download (208gb)`** ([enlace directo al paquete Faspex de TCIA](https://faspex.cancerimagingarchive.net/?context=eyJyZXNvdXJjZSI6InBhY2thZ2VzIiwidHlwZSI6ImV4dGVybmFsX2Rvd25sb2FkX3BhY2thZ2UiLCJpZCI6IjEzNDUiLCJwYXNzY29kZSI6IjE5YzRiZTU4YmJjZmU4N2E3Y2IyMGRjMDZjMTMzNDQ5MmE2MzU2MGIiLCJwYWNrYWdlX2lkIjoiMTM0NSIsImVtYWlsIjoiaGVscEBjYW5jZXJpbWFnaW5nYXJjaGl2ZS5uZXQifQ==)), que requiere instalar el cliente [**IBM Aspera Connect**](https://www.ibm.com/products/aspera/downloads#Client-deployed+software) (los NIfTI se distribuyen como paquete Aspera/Faspex).
   - Descargar y extraer la colección en una ruta externa de solo lectura fuera del repositorio (`DATA_ROOT=/ruta/externa/CFB-GBM`), verificando que las carpetas de pacientes siguen la convención `cerberus_v1` (`<paciente>/<tiempo>/<int(paciente)>_<tiempo>_<secuencia>.nii.gz`, como `Data/001`; si la extracción crea una carpeta contenedora intermedia, apuntar `paths.data_root` a la carpeta que contiene directamente los pacientes o implementar un adaptador de nombres si difieren).
   - Preparar la configuración local `"$CFG"` y validar tanto la configuración como el cableado sintético:
     ```bash
     DATA_ROOT=/ruta/externa/CFB-GBM
     WORK_DIR=storage/training                     # debe coincidir con paths.work_dir en "$CFG"
     CFG="$WORK_DIR/gtv_binary.local.json"
     ls "$DATA_ROOT" | head
     shasum -a 256 models/brats_mri_segmentation/models/model.pt
     uv run python -m cerberus_training validate --config "$CFG"
     uv run python -m cerberus_training smoke --synthetic
     ```
2. **Inventario (`inventory`):**
   ```bash
   uv run python -m cerberus_training inventory --config "$CFG" --summary "$WORK_DIR/inventory_summary.json"
   ```
   Auditar elegibles, exclusiones (`missing_channel`, `missing_label`), señales de revisión (`empty_label`, `invalid_brain_mask`) y carpetas rechazadas antes de tocar `split`.
3. **Partición (`split`):**
   ```bash
   uv run python -m cerberus_training split --config "$CFG"
   ```
   Revisar las particiones 70/15/15, los avisos de duplicados fusionados y verificar `pretraining_overlap` antes de marcarlo como `verified`.
4. **Estimación y preparación (`preflight` y `prepare`):**
   ```bash
   uv run python -m cerberus_training preflight --config "$CFG"
   uv run python -m cerberus_training prepare --config "$CFG"
   ```
   Decidir con la salida real de `preflight` si hace falta ampliar `preprocess.cache_limit_gb` en `"$CFG"` antes de correr `prepare`. Después revisar `"$WORK_DIR/prepare_report.json"` (errores `geometry_mismatch`, `non_binary_label`, etc.) y confirmar disco disponible.
5. **Piloto en GPU (`training-env/`, `cu126`):** en la máquina con GPU NVIDIA, `uv sync --project training-env --locked` instala la rueda **`cu126`** fijada en `training-env/uv.lock` (driver mínimo de compatibilidad menor CUDA 12.x según las [notas de NVIDIA CUDA 12.6](https://docs.nvidia.com/cuda/archive/12.6.1/cuda-toolkit-release-notes/index.html): **≥ `525.60.13` en Linux** y **≥ `528.33` en Windows**). Para GPU Blackwell (`sm_120`, p. ej. RTX 50xx), si `device` avisa de que la capability no está compilada en `cu126`, primero cambia el índice a `cu130` en `training-env/pyproject.toml` y regenera el lock (`uv lock --project training-env` y `uv lock --check --project training-env`) siguiendo el procedimiento de [«Entorno CUDA independiente (`training-env/`)»](#entorno-cuda-independiente-training-env) antes de sincronizar.
   Como `train --dry-run` solo ejecuta un forward sin gradiente y una ventana deslizante sobre el primer volumen de `val` ([`train.py:985`](../backend/cerberus_training/train.py#L985)), no mide el pico de VRAM del backward/optimizador ni el tiempo por época; añade un piloto corto con una copia de configuración `PILOT_CFG` que fije `training.max_epochs: 1` y un `--run-id` propio:
   ```bash
   PILOT_CFG="$WORK_DIR/gtv_binary.pilot.json"     # copia de "$CFG" con training.max_epochs: 1
   PILOT_RUN_ID=pilot-1ep
   uv sync --project training-env --locked
   uv run --project training-env python -m cerberus_training device --require-cuda
   uv run --project training-env python -m cerberus_training train --config "$CFG" --dry-run
   # En otra terminal durante el piloto para medir pico de VRAM:
   # nvidia-smi --query-gpu=timestamp,memory.used,memory.total,utilization.gpu --format=csv -l 1
   uv run --project training-env python -m cerberus_training train --config "$PILOT_CFG" --run-id "$PILOT_RUN_ID"
   cat "$WORK_DIR/runs/$PILOT_RUN_ID/metrics.jsonl"
   ```
   Revisar `seconds` en `metrics.jsonl` y el pico de VRAM medido con `nvidia-smi` para decidir si hace falta ajustar `patch_size` o `grad_accum_steps` antes de lanzar el entrenamiento largo con un `--run-id` nuevo.
6. **Entrenamiento (`train`):**
   ```bash
   RUN_ID=gtv-full-01
   uv run --project training-env python -m cerberus_training train --config "$CFG" --run-id "$RUN_ID"
   # Si se interrumpe en límite de época:
   uv run --project training-env python -m cerberus_training train --config "$CFG" --resume "$WORK_DIR/runs/$RUN_ID/checkpoints/last.pt"
   ```
7. **Evaluación frente a la línea base (`EVAL1` / `--baseline`) y exportación (`evaluate`, `export`):** fijar el mínimo de mejora exigible antes de tocar `test`; usar `val` para revisar o ajustar umbral y evaluar `test` una sola vez frente a la salida TC del modelo original (referencia imperfecta; la evaluación previa del modelo base sobre la muestra del repo corresponde a `EVAL1` en [`PLAN_VALIDEZ.md`](PLAN_VALIDEZ.md)). En `val`, la evaluación con umbral fijo y `--optimize-threshold` escriben ambas en `evaluation/val` y no se sobrescriben ([`evaluate.py:717`](../backend/cerberus_training/evaluate.py#L717)), por lo que **son alternativas mutuamente excluyentes sobre el mismo run** (ejecutar ambas devolvería código `2` en la segunda):
   ```bash
   # En val, elegir UNA sola alternativa sobre "$RUN_ID" (ambas crean evaluation/val):
   # Opción A — umbral fijo del checkpoint (0.5 por defecto):
   uv run --project training-env python -m cerberus_training evaluate --run "$WORK_DIR/runs/$RUN_ID" --split val
   # Opción B — alternativa: optimizar umbral en val, evaluarlo y guardar threshold.json para test:
   # uv run --project training-env python -m cerberus_training evaluate --run "$WORK_DIR/runs/$RUN_ID" --split val --optimize-threshold

   # Evaluación única en test (adaptado y línea base en el mismo split) y exportación:
   uv run --project training-env python -m cerberus_training evaluate --run "$WORK_DIR/runs/$RUN_ID" --split test --checkpoint best
   uv run --project training-env python -m cerberus_training evaluate --run "$WORK_DIR/runs/$RUN_ID" --split test --baseline
   uv run --project training-env python -m cerberus_training export --run "$WORK_DIR/runs/$RUN_ID"
   ```
8. **Integración en la aplicación (fuera del alcance actual):** requiere abrir un ticket nuevo tras validar el modelo y actualizar los contratos de disco y API en [`PLAN_MVP.md`](PLAN_MVP.md) (§6 y §7), `backend/cerberus_api/schemas.py` y `frontend/src/api/types.ts` (por ejemplo, para distinguir la máscara binaria GTV de las salidas BraTS TC/WT/ET). Hasta entonces, `export/` es un artefacto experimental independiente.

### 5. Decisión abierta de CP-058 (estudios elegibles que fallan en `prepare`)

- Según [`PROGRESS.md`](PROGRESS.md) (`CP-058`), si un estudio marcado como `eligible: true` en `inventory.jsonl` falla en `prepare` (p. ej. por `geometry_mismatch`, `non_binary_label`, `non_finite` o `empty_brain_mask`), `prepare` termina con código `5` y deja la caché incompleta; `train` exige todos los estudios de `train` y `val` del `splits.json` y falla con código `4`.
- **Hoy no existe un mecanismo de exclusión manual** posterior a `inventory`: cualquier cambio que altere el conjunto elegible (cambiando `eligible_records_sha256`) es rechazado con código `4` si se intenta reutilizar un `splits.json` existente (`_compare_existing` en [`splits.py:223-235`](../backend/cerberus_training/splits.py#L223-L235) y `load_training_data` en `train.py`). Además, `read_inventory` exige coherencia entre `eligible` y `exclusions`, mientras que `split` sí puede crear un `splits.json` nuevo cuando el inventario es válido y la ruta de salida (`--output` o un `paths.work_dir` nuevo) aún no existe ([`splits.py:238-250`](../backend/cerberus_training/splits.py#L238-L250)).
- **Decisión pendiente antes de entrenar sobre toda la colección:** definir si (a) se añade un mecanismo explícito y versionado de exclusión por calidad previo a `split` (generando un `inventory.jsonl` válido y un `splits.json` nuevo en un `work_dir` nuevo o con un `--output` nuevo, sin mirar resultados de `test`), o (b) los casos con `geometry_mismatch` se corrigen mediante registro previo de imágenes fuera del pipeline antes de repetir `inventory` y generar un `splits.json` nuevo.
