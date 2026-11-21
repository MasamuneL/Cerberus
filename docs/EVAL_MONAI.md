# EVAL1 · evaluación de MONAI frente a GTV

Se evaluaron los 8 estudios NIfTI disponibles en el `Data/` local, correspondientes a 5 pacientes de CFB-GBM.
Los 8 tenían GTV y al menos una secuencia utilizable por el worker. Se incluyeron 002/t0, sin T1 ni FLAIR,
y 003/t0, sin T1. El worker rellena esos canales con ceros. Usó T2* en 5 estudios y T2 turbo spin-eco
en 002/t0, 003/t0 y 004/t0 según la prioridad de los canales.

## Método

Se reutilizaron las 8 segmentaciones reales de `storage/results`, con su dispositivo de origen en la tabla.
El script comprueba que cada máscara es posterior a los pesos, las secuencias seleccionadas y la máscara
cerebral cuando está disponible. Comprueba también que el JSON asociado documenta los mismos canales.
Los pesos locales `brats_mri_segmentation/models/model.pt` tenían mtime 2026-10-20 17:56:32 UTC
y SHA-256 `860ccb3f1c21c99d0410ad8a1ac4ef6b8fab60cec0a503b0ba42675741a750ae`.

Se midió el TC (núcleo) exportado en `monai_seg.nii.gz`, que incluye las etiquetas 2 y 3 según el contrato
de disco. El worker umbraliza los canales TC y ET por separado y escribe ET al final. Si ET cae fuera
del TC umbralizado, el TC exportado incluye esos vóxeles. Se aplicó la misma definición a todas las
máscaras y se calcularon las métricas B13 de nuevo. El GTV se remuestreó al grid MONAI de 1 mm
isotrópico con vecino más cercano. Ambos volúmenes se cuentan en ese grid.

## Resultados

| Paciente | Tiempo | GTV (cm³) | TC (núcleo) (cm³) | Dice | HD95 (mm) | Recall | Precisión | Dispositivo de origen |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 001 | t0 | 33.118000 | 31.058000 | 0.856675 | 3.741657 | 0.830032 | 0.885086 | `cpu` |
| 002 | t0 | 37.574000 | 32.727000 | 0.826190 | 5.744563 | 0.772901 | 0.887371 | `mps` |
| 003 | t0 | 42.060000 | 27.779000 | 0.437979 | 16.130711 | 0.363623 | 0.550560 | `cpu` |
| 003 | t1 | 42.983000 | 38.879000 | 0.931104 | 2.449490 | 0.886653 | 0.980246 | `mps` |
| 004 | t0 | 59.319000 | 62.806000 | 0.896868 | 4.358899 | 0.923229 | 0.871971 | `mps` |
| 005 | t0 | 76.460000 | 63.237000 | 0.867893 | 5.385165 | 0.792846 | 0.958632 | `cpu` |
| 005 | t1 | 66.717000 | 55.111000 | 0.892570 | 5.385165 | 0.814935 | 0.986554 | `mps` |
| 005 | t2 | 61.720000 | 50.011000 | 0.884929 | 5.099020 | 0.800988 | 0.988523 | `cpu` |
| **Media ± DE** | | 52.493875 ± 15.610097 | 45.201000 ± 14.420701 | 0.824276 ± 0.159107 | 6.036834 ± 4.219901 | 0.773151 ± 0.172901 | 0.888618 ± 0.145133 | |
| **n** | | 8 | 8 | 8 | 8 | 8 | 8 | |

La desviación estándar (DE) es muestral. Cada estudio pesa igual, incluidos los tiempos del mismo paciente.
Se evaluaron todos los estudios sin exclusiones ni fallos.

## Límites

SegResNet se preentrenó en BraTS y aquí se aplica a CFB-GBM, con diferencias de adquisición y canales
disponibles. El TC (núcleo) de BraTS y el GTV de radioterapia delimitan regiones con criterios distintos.
La tabla mide concordancia espacial entre ambas máscaras. Los 8 estudios de 5 pacientes forman una muestra
pequeña, con tiempos repetidos por paciente, y limitan la generalización de los resultados.

## Reproducción

Ejecuta el comando desde la raíz del worktree, con las dependencias instaladas y acceso al repositorio que
contiene los datos, los pesos y las segmentaciones de referencia.

```zsh
repo=/Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus
bench="$(mktemp -d "${TMPDIR:-/tmp}/cerberus-eval1.XXXXXX")"
CERBERUS_STORAGE_DIR="$bench/storage" uv run python tools/eval/monai_all.py \
  --data-dir "$repo/Data" \
  --storage-dir "$bench/storage" \
  --models-dir "$repo/models" \
  --reuse --reuse-storage-dir "$repo/storage" \
  --out "$bench/monai.json"
```

`monai.json` guarda las métricas sin redondear, el resumen, los dispositivos, los canales, el origen de
cada máscara, las exclusiones y los fallos. Tres ejecuciones con el mismo storage previo dieron un JSON
idéntico y reprodujeron la tabla a ±1e-6. `--no-reuse` fuerza inferencia secuencial con el mismo
`run_segmentation` del worker y guarda las nuevas máscaras en `--storage-dir`.
