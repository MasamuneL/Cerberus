# Cerberus

Análisis exploratorio, visualización 3D y segmentación de glioblastoma sobre el dataset **CFB-GBM** (The Cancer Imaging Archive).

Además del notebook, Cerberus es ahora una **app web**: backend **FastAPI + arq/Redis + MONAI** y frontend
**React + Vite + TypeScript + [Niivue](https://github.com/niivue/niivue)** como visor de imagen médica.

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
├── backend/
│   ├── cerberus_api/      # FastAPI (main, routers/, servicios, worker arq)
│   └── tests/             # pytest
├── frontend/              # React + Vite + TS + Niivue
├── docs/
│   ├── PLAN_MVP.md        # plan, contratos y tickets del MVP
│   └── PROGRESS.md        # bitácora de checkpoints
├── storage/               # resultados, uploads, staging (generado, ignorado)
├── AGENTS.md / CLAUDE.md  # instrucciones para agentes de código
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

## App web

### Requisitos

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node 20+ y npm
- Redis (`brew install redis`)
- [Git LFS](https://git-lfs.com) (para la muestra en `Data/001`)

### Arranque (4 terminales, desde la raíz)

```bash
uv sync                                                    # una vez: deps Python
redis-server                                               # terminal 1
uv run arq cerberus_api.worker.WorkerSettings              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --port 8000  # terminal 3: API
cd frontend && npm install && npm run dev                  # terminal 4: UI
```

- UI: <http://localhost:5173>
- Documentación interactiva de la API: <http://localhost:8000/docs>
- Si el puerto 5173 está ocupado: `cd frontend && npx vite --port 5180`
  (agrega ese origen a `CERBERUS_CORS_ORIGINS` si llamas a la API sin el proxy de Vite).

### Arquitectura

```
Navegador (React + Niivue, :5173)
   │  /api/*  (proxy de Vite en dev)
   ▼
FastAPI (:8000) ──lee/escribe──► Data/   storage/
   │ encola (arq)
   ▼
Redis (:6379) ◄── worker arq ──► MONAI SegResNet (torch, cpu/mps/cuda)
                         └─────► dcm2niix (conversión DICOM)
```

### Funcionalidades

- Lista de estudios (paciente / tiempo) detectados en `Data/` y `storage/`.
- Visor multiplanar (axial/coronal/sagital) y 3D con Niivue, con overlay del GTV.
- Volumetría (planimetría vs ABC/2) y evaluación **RANO 2.0** longitudinal por paciente.
- Segmentación **MONAI** (`brats_mri_segmentation`) como job asíncrono (arq), con progreso.
- Subida de volúmenes NIfTI.
- Ingesta de ZIP DICOM **anonimizada** (conversión con dcm2niix y confirmación de series).

### Endpoints principales (prefijo `/api`)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/studies` | Lista de estudios |
| GET | `/api/studies/{patient}/{timepoint}` | Detalle de un estudio (secuencias disponibles) |
| GET/HEAD | `/api/studies/{patient}/{timepoint}/files/{name}.nii.gz` | Descarga un volumen (secuencia o `monai_seg`) |
| GET | `/api/studies/{patient}/{timepoint}/volumetry` | Volumetría GTV (planimetría, ABC/2) |
| GET | `/api/patients/{patient}/longitudinal` | Serie longitudinal + clasificación RANO 2.0 |
| POST | `/api/studies/{patient}/{timepoint}/segmentation` | Encola la segmentación MONAI (202) |
| GET | `/api/studies/{patient}/{timepoint}/segmentation` | Resultado de la segmentación |
| GET | `/api/jobs/{job_id}` | Estado / progreso de un job |
| POST | `/api/uploads` | Sube NIfTI (201) o ZIP DICOM (202, ingesta encolada) |
| GET | `/api/uploads/{upload_id}` | Estado de una ingesta DICOM |
| GET/HEAD | `/api/uploads/{upload_id}/series/{index}.nii.gz` | Vista previa de una serie convertida |
| POST | `/api/uploads/{upload_id}/confirm` | Confirma el mapeo de series → crea el estudio |
| DELETE | `/api/uploads/{upload_id}` | Descarta una ingesta |

### Variables de entorno

Prefijo `CERBERUS_`; los valores por defecto son relativos a la raíz del repo.

| Variable | Default |
|---|---|
| `CERBERUS_DATA_DIR` | `Data` |
| `CERBERUS_STORAGE_DIR` | `storage` |
| `CERBERUS_MODELS_DIR` | `models` |
| `CERBERUS_REDIS_URL` | `redis://localhost:6379` |
| `CERBERUS_MAX_UPLOAD_MB` | `2048` |
| `CERBERUS_MAX_ZIP_UNCOMPRESSED_MB` | `4096` |
| `CERBERUS_CORS_ORIGINS` | `["http://localhost:5173"]` |

## Resultados de referencia (paciente 001/t0)

| Métrica | Valor |
|---|---|
| GTV (planimetría) | 33.14 cm³ |
| ABC/2 | 51.38 cm³ (+55 % vs planimetría) |
| MONAI WT / TC / ET | 53.51 / 31.01 / 20.99 cm³ |
| Dice vs GTV | TC 0.857 · WT 0.718 (rango inter-observador típico 0.72–0.88) |
| Tiempo de inferencia | ~13–18 s en Apple MPS |

## Desarrollo en equipo

El proyecto se desarrolla por tickets con trazabilidad entre dispositivos y agentes (Codex, Claude Code, etc.):

- [`AGENTS.md`](AGENTS.md) — reglas para cualquier agente o colaborador.
- [`docs/PLAN_MVP.md`](docs/PLAN_MVP.md) — alcance, arquitectura, contratos de API y tickets.
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — checkpoints; sigue el protocolo de §12 del plan (reclamar ticket, registrar CP al terminar).

Checks obligatorios antes de un PR:

```bash
uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -m "not slow"
cd frontend && npm run build                               # tsc -b && vite build
```

Los tests lentos (`uv run pytest -m slow`) requieren `Data/001` (Git LFS) y los pesos MONAI en `models/`.

## Datos

El repositorio solo incluye al **paciente 001** como muestra (~770 MB vía Git LFS) para no exceder la cuota de LFS.
Para el resto de pacientes (002–005, varios tiempos), descarga la colección **CFB-GBM** desde
[TCIA](https://www.cancerimagingarchive.net/) y colócala en `Data/` respetando la estructura de arriba.
El notebook detecta automáticamente todo lo que haya en `Data/*/t*/*.nii.gz`.

**Privacidad DICOM:** los ZIP DICOM se anonimizan al ingerirse y los archivos originales se eliminan tras la
conversión. Aun así, no subas imágenes con texto identificable "quemado" en los píxeles (burned-in).

Uso de los datos sujeto a la licencia y política de citación de TCIA para la colección CFB-GBM.
