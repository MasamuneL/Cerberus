# Cerberus

Análisis exploratorio, visualización 3D y segmentación de glioblastoma sobre el dataset **CFB-GBM** (The Cancer Imaging Archive).

Proyecto de Big Data — UDG, 5.º semestre.

## Qué incluye

- **`cerberus_eda.py`** — notebook [marimo](https://marimo.io) con:
  - Inventario de la data (secuencias, shape, spacing, dtype).
  - Cortes axial / coronal / sagital sincronizados con máscara GTV superpuesta.
  - Volumetría tumoral (planimetría vs ABC/2, umbrales RANO 2.0).
  - Líneas base clásicas de segmentación (Otsu, K-Means).
  - Segmentación con **MONAI Model Zoo `brats_mri_segmentation`** (SegResNet).
  - Iso-superficies 3D con **Mayavi** (offscreen) y Plotly interactivo.
- **`cerberus_mayavi.py`** — escena Mayavi reutilizable; también abre una ventana Qt interactiva a partir de un `.npz` exportado por el notebook.

> ⚠️ La máscara de referencia del dataset es el **GTV de radioterapia** (puede incluir cavidad de resección y excluye edema), no el "volumen tumoral" genérico.

## Estructura

```
Cerberus/
├── cerberus_eda.py        # notebook marimo principal
├── cerberus_mayavi.py     # escena 3D Mayavi
├── Data/
│   └── 001/t0/            # muestra versionada con Git LFS
│       ├── 1_t0_t1gd.nii.gz
│       ├── 1_t0_flair.nii.gz
│       ├── 1_t0_gtv.nii.gz
│       └── ...
├── models/                # pesos MONAI (se descargan solos, ignorado)
├── pyproject.toml
└── uv.lock
```

Archivos de datos: `Data/<paciente>/<tiempo>/<n>_<tiempo>_<secuencia>.nii.gz`
(secuencias: `t1gd`, `t1eg`, `t1tse`, `t2tse`, `t2star`, `flair`, `adc`, `ct`, `rtdose`, `brain_mask`, `gtv`).

## Instalación

Requisitos: Python 3.11, [uv](https://docs.astral.sh/uv/) y [Git LFS](https://git-lfs.com).

```bash
git lfs install
git clone https://github.com/MasamuneL/Cerberus.git
cd Cerberus
uv sync
```

Si clonaste sin LFS, los `.nii.gz` serán punteros de texto; descárgalos con:

```bash
git lfs pull
```

## Uso

```bash
# Editar / explorar el notebook
uv run marimo edit cerberus_eda.py

# Modo app (solo lectura)
uv run marimo run cerberus_eda.py

# Ventana Mayavi interactiva con una escena exportada desde el notebook
uv run python cerberus_mayavi.py escena.npz
```

La primera ejecución de la celda MONAI descarga el bundle `brats_mri_segmentation` en `models/`.

## Datos

El repositorio solo incluye al **paciente 001** como muestra (~770 MB vía Git LFS) para no exceder la cuota de LFS.
Para el resto de pacientes (002–005, varios tiempos), descarga la colección **CFB-GBM** desde
[TCIA](https://www.cancerimagingarchive.net/) y colócala en `Data/` respetando la estructura de arriba.
El notebook detecta automáticamente todo lo que haya en `Data/*/t*/*.nii.gz`.

Uso de los datos sujeto a la licencia y política de citación de TCIA para la colección CFB-GBM.
