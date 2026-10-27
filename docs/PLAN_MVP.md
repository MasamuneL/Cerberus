# Plan MVP — Cerberus Web (FastAPI + React + Niivue)

## Contexto

Hoy Cerberus es un notebook marimo (`cerberus_eda.py`) que inventaría el dataset CFB-GBM (NIfTI), calcula
volumetría del GTV, segmenta con MONAI SegResNet y muestra cortes y 3D. Queremos convertirlo en una app web
para el equipo. El stack ya está decidido: **FastAPI + arq/Redis** (backend Python, para reutilizar MONAI)
y **React + Vite + TypeScript + Niivue** (frontend). Además debe aceptar **DICOM** convirtiéndolo a NIfTI.

El equipo usa distintas IAs (Claude Code, Codex, etc.), así que el plan tiene que funcionar como **contrato
autocontenido**: carpetas, contratos de API, tickets con criterios de aceptación y comandos de verificación.

Estado del repo al 27-10-2026: en `pyproject.toml` y `uv.lock` ya están agregadas
fastapi, uvicorn[standard], python-multipart, arq, pydantic-settings y dcm2niix, más ruff, pyright, pytest
y httpx como dependencias de desarrollo.


---

## 1. Alcance del MVP

**Incluye**
- Listar los estudios (paciente/tiempo) que hay en `Data/`.
- Visor multiplanar (axial/coronal/sagital + 3D) de cualquier secuencia, con overlay del GTV.
- Volumetría del GTV (planimetría, ABC/2, fracción cerebral, medible RANO) y seguimiento longitudinal RANO 2.0.
- Segmentación MONAI SegResNet como job asíncrono, con su overlay en el visor y volúmenes WT/TC/ET.
- Subida de un NIfTI suelto (indicando la secuencia).
- Subida de un `.zip` DICOM: detectar series, convertir a NIfTI, sugerir la secuencia, el usuario confirma
  y se guarda en `Data/`.

**No incluye** (fase 2): auth/usuarios, base de datos, Otsu/K-Means en la app, edema FLAIR, skull-stripping
automático, registro entre series, RTSTRUCT (rt-utils), exportar DICOM SEG, despliegue/Docker, Mayavi.

## 2. Decisiones fijas (no reabrir sin hablar con el equipo)

| Tema | Decisión |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, arq + Redis para jobs |
| Gestión de dependencias Python | `uv` (prohibido usar pip directo) |
| Frontend | React + Vite + TypeScript, Niivue, CSS plano (sin librería de UI), `fetch` nativo, sin Redux |
| Formato interno | Solo NIfTI (`.nii.gz`). DICOM es solo formato de entrada |
| Fuente de verdad de los datos | El sistema de archivos (`Data/`); no hay base de datos en el MVP |
| Idioma | Identificadores en inglés; comentarios, docs y textos de la UI en español |
| Paquete backend | `backend/cerberus_api/`, instalable vía hatchling desde el `pyproject.toml` raíz |

## 3. Arquitectura

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

## 4. Estructura de carpetas objetivo

```
Cerberus/
├── AGENTS.md  CLAUDE.md  README.md  pyproject.toml  uv.lock
├── cerberus_eda.py  cerberus_mayavi.py         # se quedan como están (referencia)
├── docs/PLAN_MVP.md  docs/PROGRESS.md
├── backend/
│   ├── cerberus_api/
│   │   ├── __init__.py
│   │   ├── config.py        # Settings (pydantic-settings)
│   │   ├── nifti.py         # load_nifti(): carga tipada (usar en vez de nib.load)
│   │   ├── sequences.py     # SEQ_INFO, MRI_SEQS, regex de validación
│   │   ├── catalog.py       # escaneo de Data/ → Study
│   │   ├── volumetry.py     # volumetría GTV + RANO
│   │   ├── segmentation.py  # MONAI (función pura, testeable)
│   │   ├── dicom.py         # zip seguro, agrupar series, clasificar, dcm2niix
│   │   ├── staging.py       # manifest de uploads DICOM
│   │   ├── schemas.py       # modelos Pydantic de la API
│   │   ├── worker.py        # arq WorkerSettings + tareas
│   │   ├── deps.py          # get_settings, get_redis (pool lazy)
│   │   ├── main.py          # create_app(), CORS, routers
│   │   └── routers/{studies,jobs,uploads}.py
│   └── tests/
│       ├── conftest.py      # fixtures make_nifti / make_study
│       └── test_*.py
├── frontend/
│   ├── package.json  vite.config.ts  tsconfig.json  index.html
│   └── src/
│       ├── main.tsx  App.tsx  styles.css
│       ├── api/{types.ts,client.ts}
│       ├── hooks/useJob.ts
│       └── components/{StudyList,Viewer,VolumetryPanel,SegmentationPanel,UploadPanel}.tsx
├── Data/                    # NIfTI (001 versionado con LFS)
├── models/                  # pesos MONAI (ignorado)
└── storage/                 # ignorado: results/, staging/, tmp/
```

## 5. Configuración y comandos

Variables de entorno (prefijo `CERBERUS_`; los valores por defecto son relativos a la raíz del repo):

| Variable | Default |
|---|---|
| `CERBERUS_DATA_DIR` | `Data` |
| `CERBERUS_STORAGE_DIR` | `storage` |
| `CERBERUS_MODELS_DIR` | `models` |
| `CERBERUS_REDIS_URL` | `redis://localhost:6379` |
| `CERBERUS_MAX_UPLOAD_MB` | `2048` |
| `CERBERUS_MAX_ZIP_UNCOMPRESSED_MB` | `4096` |
| `CERBERUS_CORS_ORIGINS` | `["http://localhost:5173"]` |

Comandos (todos desde la raíz):

```bash
uv sync                                                    # deps Python (incluye el paquete en modo editable)
redis-server                                               # terminal 1
uv run arq cerberus_api.worker.WorkerSettings              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --port 8000  # terminal 3: API (docs en /docs)
cd frontend && npm install && npm run dev                  # terminal 4: UI en :5173

# Checks obligatorios antes de un PR
uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -m "not slow"
cd frontend && npm run build                               # tsc -b && vite build
```

Configuración que agrega B0 en `pyproject.toml`:
- `[build-system]` hatchling; `[tool.hatch.build.targets.wheel] packages = ["backend/cerberus_api"]`.
- `[tool.ruff]` line-length 120, target-version py311; lint select `E,F,I,UP,B`.
- `[tool.pyright]` include `["backend"]`, typeCheckingMode `"standard"`, extraPaths `["backend/tests"]`. No se usa strict porque
  nibabel/monai no tienen tipos y generarían ruido.
- `[tool.pytest.ini_options]` testpaths `["backend/tests"]`, markers `slow`.

## 6. Almacenamiento en disco (contrato)

```
Data/<patient>/<timepoint>/<int(patient)>_<timepoint>_<sequence>.nii.gz   # misma convención actual
storage/results/<patient>/<timepoint>/monai_seg.nii.gz                    # mapa de etiquetas uint8
storage/results/<patient>/<timepoint>/monai_seg.json                      # SegmentationResult
storage/staging/<upload_id>/manifest.json                                 # UploadManifest
storage/staging/<upload_id>/series/<index>.nii.gz                         # series ya convertidas
storage/tmp/<uuid>/                                                       # DICOM extraído; se borra SIEMPRE (finally)
```

Validación (en `sequences.py`, se usa en todos los endpoints antes de tocar el disco):
- `patient`: `^\d{3}$` · `timepoint`: `^t\d{1,2}$` (ambas con `re.ASCII`: solo dígitos 0-9) · `sequence` ∈ claves de `SEQ_INFO`
  (`t1gd, t1eg, t1tse, t2tse, t2star, flair, adc, ct, rtdose, brain_mask, gtv`).
- Nombre de archivo servible: secuencia válida o `monai_seg`. Cualquier otro valor → 404. Nunca se construye
  una ruta con texto del usuario sin validarlo antes (evita path traversal).

Etiquetas de `monai_seg.nii.gz`: `0` fondo · `1` edema (WT−TC) · `2` núcleo no realzante (TC−ET) · `3` realce (ET).
Se asignan en orden: WT→1, luego TC→2, luego ET→3.

## 7. Contratos de la API (prefijo `/api`)

`types.ts` en el frontend refleja **exactamente** `schemas.py`. Si cambias un contrato, en el mismo PR
actualizas: `schemas.py`, `types.ts` y esta sección.

```jsonc
// Study
{ "patient": "001", "timepoint": "t0",
  "sequences": ["adc","brain_mask","ct","flair","gtv","rtdose","t1eg","t1gd","t2star"],
  "has_gtv": true, "has_brain_mask": true, "has_segmentation": false }

// StudyDetail = Study + volumes
{ ...Study, "volumes": [ { "sequence": "t1gd", "label": "T1 con gadolinio (realce)",
    "shape": [512,512,208], "spacing_mm": [0.5,0.5,1.0], "dtype": "int16" } ] }

// Volumetry (cálculo a resolución nativa, igual que el notebook)
{ "gtv_cm3": 41.2, "brain_cm3": 1210.5, "fraction_pct": 3.4,
  "lr_mm": 52.0, "ap_mm": 61.5, "si_mm": 48.0, "abc2_cm3": 76.7, "abc2_error_pct": 86.2,
  "components": 1, "rano_measurable": true, "spacing_ok": true }

// LongitudinalPoint
{ "timepoint": "t1", "gtv_cm3": 30.1, "change_vs_t0_pct": -26.9, "rano": "SD" }  // PD|PR|MR|SD; t0 → change 0, rano null

// SegmentationResult (monai_seg.json)
{ "device": "mps", "created_at": "2026-10-27T18:00:00Z",
  "channels": [ { "model_channel": "T1c", "sequence": "t1gd" }, { "model_channel": "T2", "sequence": null } ],
  "volumes_cm3": { "wt": 80.3, "tc": 40.1, "et": 22.0 },
  "dice_vs_gtv": { "tc": 0.71, "wt": 0.55 },          // null si no hay gtv
  "warnings": ["Canal T2 faltante: se usaron ceros", "Sin brain_mask: no hay skull-strip"] }

// JobStatus
{ "job_id": "…", "status": "queued|in_progress|complete|failed|not_found", "result": {…}|null, "error": "…"|null }

// UploadManifest
{ "upload_id": "…", "status": "processing|ready|failed", "error": null,
  "series": [ { "index": 0, "modality": "MR", "description": "AX FLAIR", "n_files": 208,
                "shape": [256,256,208], "spacing_mm": [1,1,1], "converted": true,
                "suggested_sequence": "flair" } ] }
```

| Método y ruta | Entrada | Respuesta |
|---|---|---|
| `GET /api/health` | — | `{"status":"ok"}` |
| `GET /api/studies` | — | `Study[]` ordenado por patient, timepoint |
| `GET /api/studies/{patient}/{timepoint}` | — | `StudyDetail` · 404 |
| `GET /api/studies/{patient}/{timepoint}/files/{name}.nii.gz` | name = secuencia o `monai_seg` | binario `application/gzip` · 404 |
| `GET /api/studies/{patient}/{timepoint}/volumetry` | — | `Volumetry` · 404 si falta gtv o brain_mask |
| `GET /api/patients/{patient}/longitudinal` | — | `LongitudinalPoint[]` (solo los tiempos con gtv+brain_mask) |
| `POST /api/studies/{patient}/{timepoint}/segmentation` | — | 202 `{"job_id"}` · 422 si no hay ninguna secuencia MRI de canal |
| `GET /api/studies/{patient}/{timepoint}/segmentation` | — | `SegmentationResult` · 404 |
| `GET /api/jobs/{job_id}` | — | `JobStatus` |
| `POST /api/uploads` | multipart: `file`, `patient`, `timepoint`, `sequence?` | `.nii`/`.nii.gz` (sequence obligatoria) → 201 `Study`; `.zip` → 202 `{"upload_id","job_id"}`; 409 si el archivo ya existe; 413 si excede el tamaño; 415 con otra extensión |
| `GET /api/uploads/{upload_id}` | — | `UploadManifest` |
| `GET /api/uploads/{upload_id}/series/{index}.nii.gz` | — | NIfTI de la serie (vista previa) |
| `POST /api/uploads/{upload_id}/confirm` | `{"patient","timepoint","mapping":{"0":"t1gd","2":"flair"}}` | 201 `Study`; mueve a `Data/` y borra el staging · 409 si existe o hay secuencias repetidas en el mapping |
| `DELETE /api/uploads/{upload_id}` | — | 204 |

Jobs de arq: `segment_study(ctx, patient, timepoint) -> dict` y `ingest_dicom(ctx, upload_id, zip_path) -> dict`.
El trabajo pesado se corre con `await asyncio.to_thread(...)`. `job_timeout = 1800`.
`GET /api/jobs` usa `arq.jobs.Job(job_id, redis).status()`; si es `complete`, llama `result_info()` y mapea
`success=False` → `failed`, poniendo el `str` de la excepción en `error`.

## 8. Tickets

Cada ticket = una rama `feat/<ID>-<slug>` y un PR. "Hecho" = los criterios se cumplen y pasan los checks de §5.

### Backend

**B0 · Bootstrap** (bloquea todo)
- `pyproject.toml`: secciones de §5. `.gitignore`: agregar `storage/`, `frontend/node_modules/`, `frontend/dist/`.
- Crear `backend/cerberus_api/__init__.py` y `backend/tests/conftest.py`, con fixtures:
  - `make_nifti(path, data: np.ndarray, zooms=(0.5,0.5,1.0))`: affine diagonal con los zooms.
  - `make_study(root, patient="001", timepoint="t0", seqs=(...), shape=(40,40,20))`: escribe archivos con la
    convención de §6. `gtv` = cubo binario conocido y `brain_mask` = caja más grande.
- `AGENTS.md`, `CLAUDE.md` y `docs/PLAN_MVP.md` ya existen (no recrear).
- Aceptación: `uv sync` instala el paquete; `uv run python -c "import cerberus_api"` funciona; `uv run pytest`
  corre (0 tests está bien).

**B1 · config + sequences**
- `config.py`: `Settings(BaseSettings)` con env_prefix `CERBERUS_`; resuelve las rutas relativas contra la raíz
  del repo (`Path(__file__).resolve().parents[2]`). `get_settings()` con `lru_cache`.
- `sequences.py`: copiar `SEQ_INFO` y `MRI_SEQS` de `cerberus_eda.py:83-96`, más las regex de §6 y
  `validate_patient/timepoint/sequence()`, que lanzan `ValueError`.
- Tests: env override; regex que aceptan/rechazan (`"001"`, `"1"`, `"../x"`, `"t0"`, `"t10"`, `"tx"`).

**B2 · catalog** (depende de B1)
- Portar el inventario de `cerberus_eda.py:100-120`, pero con regex `(\d+)_(t\d+)_(.+)\.nii\.gz` y leyendo
  solo el header (`nib.load(f).header`).
- API: `list_studies(data_dir) -> list[Study]`, `get_study(data_dir, results_dir, p, t) -> StudyDetail | None`,
  `sequence_path(data_dir, p, t, seq) -> Path | None`. `has_segmentation` = existe `monai_seg.nii.gz`.
- Ignora archivos que no cumplen la convención, sin fallar.
- Tests con `make_study`: dos estudios, secuencias ordenadas, archivo basura ignorado, shape/spacing correctos.

**B3 · volumetry** (depende de B1)
- `gtv_volumetry(gtv_path, brain_path) -> Volumetry`: portar el cuerpo del loop de `cerberus_eda.py:209-235`
  sin cambiar las fórmulas.
- `rano_category(pct) -> str`: portar `cerberus_eda.py:300-307`, pero devolviendo `"PD"|"PR"|"MR"|"SD"`.
- `longitudinal(data_dir, patient) -> list[LongitudinalPoint]`: lógica de `cerberus_eda.py:309-312`, con base t0.
- Tests: un cubo de 10×10×10 vóxeles a 1 mm da `gtv_cm3 == 1.0` y ABC/2 `== 0.5`; con spacing
  0.5×0.5×1 da 0.25; fracción correcta; `rano_category` en sus bordes (40, -40, -65, 39.9).

**B4 · API de lectura** (depende de B2, B3)
- `main.py`: `create_app()` con CORS desde settings, routers montados en `/api`, y `app = create_app()`.
- `routers/studies.py`: endpoints GET de §7 (studies, detail, files, volumetry, longitudinal).
  `files` usa `FileResponse` con `media_type="application/gzip"`.
- Tests con `TestClient` y `dependency_overrides` de settings apuntando a `tmp_path`: lista, detalle, descarga
  de un archivo (bytes == archivo), 404 para `name="../../etc/passwd"`, 404 para una secuencia inexistente,
  volumetry 404 sin gtv.

**B5 · segmentation** (depende de B2)
- `run_segmentation(study_files: dict[str, Path], out_dir: Path, models_dir: Path, predictor=None) -> SegmentationResult`.
  1. Canales con `CHANNEL_MAP = {"T1c": ("t1gd",), "T1": ("t1eg","t1tse"), "T2": ("t2tse","t2star"), "FLAIR": ("flair",)}`
     (como en `cerberus_eda.py:755-760`). Si no hay ninguno → `ValueError`.
  2. Grid de referencia: el primer canal disponible (prioridad t1gd) se pasa a 1 mm isotrópico con
     `nibabel.processing.resample_to_output(img, voxel_sizes=(1,1,1), order=1)`.
  3. Cada canal y `brain_mask`/`gtv` se remuestrean a ese grid con `resample_from_to(img, (shape, affine), order=1)`
     (máscaras con `order=0`, y luego `> 0.5`). Esto generaliza el `stride=2` del notebook a cualquier spacing.
  4. Multiplicar por `brain_mask` si existe; si no, agregar un warning. Canal faltante = ceros + warning.
  5. `NormalizeIntensity(nonzero=True, channel_wise=True)`, red e inferencia igual que en
     `cerberus_eda.py:761-772`: SegResNet con los mismos hiperparámetros, `sliding_window_inference((240,240,160), 1, overlap=0.5)`,
     sigmoide > 0.5, y el dispositivo cuda → mps → cpu.
  6. `predictor`: callable `np.ndarray[4,X,Y,Z] -> np.ndarray[3,X,Y,Z]` (probabilidades TC, WT, ET). Si es `None`,
     descarga el bundle (`monai.bundle.download`, como en `cerberus_eda.py:751-753`) y usa SegResNet.
     torch y monai se importan dentro de la función.
  7. Escribir `monai_seg.nii.gz` (etiquetas de §6, affine del grid de referencia) y `monai_seg.json`. Si existe
     `gtv`, calcular el Dice TC y WT con la fórmula `dice` de `cerberus_eda.py:178-181`.
- Tests (sin red): un `predictor` falso que devuelve cubos conocidos → verificar etiquetas, volúmenes y warnings
  por canales faltantes, y que el affine de salida corresponda a 1 mm. Test `@pytest.mark.slow` con el modelo
  real sobre `Data/001/t0`.

**B6 · jobs** (depende de B4, B5)
- `deps.py`: `get_redis()` crea un pool arq de forma lazy (una sola vez, con `create_pool(RedisSettings.from_dsn(url))`).
  La app arranca aunque Redis esté apagado.
- `worker.py`: `WorkerSettings` con `functions=[segment_study, ingest_dicom]`, `redis_settings`, `job_timeout=1800`.
- `routers/jobs.py` y los POST/GET de segmentación en `studies.py`.
- Tests: override de `get_redis` con un fake que registra `enqueue_job`; POST devuelve 202 y llama
  `segment_study`; GET de segmentación lee el json.

**B7 · subida de NIfTI** (depende de B4)
- `routers/uploads.py`: `POST /api/uploads` para `.nii`/`.nii.gz`. Escribe en streaming a `storage/tmp` cortando
  al pasar `MAX_UPLOAD_MB` (413), valida con `nib.load`, asegura 3D, guarda en `.nii.gz` en la ruta de §6
  y devuelve 409 si ya existe.
- Tests: subida válida → aparece en `GET /api/studies`; secuencia inválida → 422; repetida → 409;
  archivo que no es NIfTI → 422.

**B8 · ingesta DICOM** (depende de B6, B7)
- `dicom.py`:
  - `safe_extract(zip_path, dest, max_members=20000, max_bytes=…)`: rechaza rutas absolutas, `..` y symlinks,
    y verifica la suma de `file_size` **antes** de extraer.
  - `group_series(root) -> list[SeriesGroup]`: `pydicom.dcmread(f, stop_before_pixels=True)`; omite
    `InvalidDicomError`; agrupa por `SeriesInstanceUID`. Solo conserva `Modality`, `SeriesDescription`,
    `ProtocolName`, `ContrastBolusAgent` (si existe), `SeriesNumber` y la lista de archivos.
  - `suggest_sequence(tags) -> str | None`: reglas en orden sobre `description + protocol` en minúsculas:
    `Modality=="CT"`→`ct`; `RTDOSE`/`RTSTRUCT`/otras → `None`; `flair`→`flair`; `adc|apparent`→`adc`;
    `t2*|t2star|swi|gre` sin `flair` (y `gre` solo si no hay `t1`; CP-013)→`t2star`; `t2`→`t2tse`; `t1` con (`gd|gad|post|+c|contrast|ce` o
    `ContrastBolusAgent` presente)→`t1gd`; `mprage|gre|tfe|spgr` con `t1`→`t1eg`; `t1`→`t1tse`; si nada coincide → `None`.
  - `convert_series(files, out_dir)`: copia los archivos a una carpeta por serie y corre
    `dcm2niix -z y -b n -i y -f series -o <out> <dir>` (binario en `Path(sys.executable).parent / "dcm2niix"`,
    con fallback a `shutil.which`). Toma `series.nii.gz` o, si no existe, el primer `*.nii.gz`; si no hay ninguno,
    `converted=False`.
- `staging.py`: leer/escribir `manifest.json` (`UploadManifest`).
- Job `ingest_dicom`: `safe_extract` → `group_series` → convertir → manifest `ready`. En `finally`, `rmtree` del
  tmp y del zip. Si hay error, manifest `failed` con mensaje.
- Endpoints de uploads para `.zip`, manifest, preview, confirm y delete de §7.
- **Reglas de datos personales (obligatorias):** el DICOM nunca sale de `storage/tmp`; el manifest no guarda
  `PatientName/PatientID/PatientBirthDate/InstitutionName/AccessionNumber/StudyDate` ni UIDs; dcm2niix siempre
  con `-b n` y `-f series`; no se loguean headers.
- Tests: `suggest_sequence` paramétrico (≥ 12 casos); `safe_extract` rechaza `../evil` y un zip que excede el
  límite; un DICOM sintético con pydicom (`Dataset` MR con PatientName) → `group_series` → el manifest serializado
  **no** contiene el nombre; `confirm` mueve los archivos y borra el staging; mapping con secuencias repetidas → 409.
  Conversión real con dcm2niix marcada `slow`.

### Frontend

**F0 · Scaffold** (paralelo a B1–B3)
- Crear a mano `frontend/` (sin plantillas interactivas). `npm install react react-dom @niivue/niivue` y
  `npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom`. Versiones verificadas al
  27-10-2026: react 19.3.1, vite 8.3.5, @niivue/niivue 0.69.0. Fijar las versiones exactas en `package.json`.
- `vite.config.ts`: `server.proxy = { "/api": "http://localhost:8000" }`. Scripts: `dev`, `build` (`tsc -b && vite build`), `preview`.
- Aceptación: `npm run dev` muestra "Cerberus" y `npm run build` pasa.

**F1 · API client** (depende de F0; usa §7 como contrato y no necesita el backend listo)
- `api/types.ts`: interfaces idénticas a §7. `api/client.ts`: funciones tipadas (`listStudies`, `getStudy`,
  `fileUrl(p,t,name)`, `getVolumetry`, `getLongitudinal`, `startSegmentation`, `getSegmentation`, `getJob`,
  `uploadFile`, `getUpload`, `confirmUpload`, `deleteUpload`). Lanzan `ApiError(status, detail)` en respuestas no 2xx.
- `hooks/useJob.ts`: hace polling a `getJob` cada 2 s hasta `complete|failed|not_found` y limpia el intervalo al desmontar.

**F2 · StudyList** (depende de F1, B4)
- Barra lateral agrupada por paciente. Cada tiempo muestra badges (GTV, Seg). Al hacer clic, `App` guarda
  el estudio seleccionado.

**F3 · Viewer** (depende de F1, B4)
- `<canvas>` con Niivue: `new Niivue({...})`, `attachToCanvas(canvas)`,
  `loadVolumes([{ url: fileUrl(...), colormap: "gray" }, ...overlays])`, `setSliceType(nv.sliceTypeMultiplanar)`.
  **Antes de escribir, verificar las firmas en `node_modules/@niivue/niivue` (archivo `.d.ts`)**, porque la API
  cambia entre versiones.
- API verificada en @niivue/niivue 0.69.0 (F0, CP-002), tipos en `build/niivue/index.d.ts`:
  `import { Niivue, SLICE_TYPE, NVImage } from "@niivue/niivue"`; `new Niivue(opts?: Partial<NVConfigOptions>)`;
  `await nv.attachToCanvas(canvas)` (es async: esperar antes de `loadVolumes`);
  `loadVolumes(list: ImageFromUrlOptions[])` con `{url, name?, colormap?, opacity?, cal_min?, cal_max?, colormapLabel?}`;
  `setSliceType(SLICE_TYPE.MULTIPLANAR | AXIAL | CORONAL | SAGITTAL | RENDER)`; `setOpacity(volIdx, x)`;
  `removeVolumeByIndex(i)`; `updateGLVolume()`. Mapa de etiquetas: `nv.volumes[i].setColormapLabel(cm: ColorMap)`
  y luego `nv.updateGLVolume()` (no existe en la clase `Niivue`), donde `ColorMap = {R,G,B,A,I: number[], labels?}`.
- Controles: selector de secuencia (todas menos gtv/brain_mask; t1gd por defecto), toggle GTV (colormap `red`,
  opacidad con slider de 0 a 1, 0.4 por defecto), toggle segmentación (`monai_seg`; usar un colormap de etiquetas
  si la versión lo soporta, si no `warm` con `cal_min 0.5`, `cal_max 3`), y `rtdose` con colormap `jet`.
  Botones de vista: multiplanar / axial / coronal / sagital / 3D.
- Volver a cargar los volúmenes cuando cambie el estudio o la secuencia, sin crear otro `Niivue`.

**F4 · VolumetryPanel** (depende de F1, B4)
- Tabla con `Volumetry` y una tabla longitudinal con su categoría RANO (color por categoría). Si hay 404,
  mostrar "Este estudio no tiene GTV/brain_mask".

**F5 · SegmentationPanel** (depende de F3, B6)
- Botón "Segmentar con MONAI" → `startSegmentation` → `useJob`. Muestra el estado y, al terminar, carga
  `getSegmentation`: volúmenes WT/TC/ET, Dice, canales usados y los warnings (destacados). Activa el overlay en el Viewer.

**F6 · UploadPanel** (depende de F1, B7, B8)
- Formulario: archivo, patient y timepoint, con la misma validación regex en el cliente, y `sequence` (visible
  solo para NIfTI).
- Si es `.zip`: hace polling del manifest y muestra una tabla de series (descripción, modalidad, n archivos, shape)
  con un `<select>` de secuencia precargado con `suggested_sequence` (opción "ignorar"). El botón "Confirmar" se
  bloquea si hay secuencias repetidas.
- Aviso visible: "Los archivos DICOM se anonimizan y se eliminan tras convertirse; no subas imágenes con texto
  identificable quemado."

### Docs

**D1 · README** (al final): sección "App web" con los comandos de §5 y un diagrama de §3.

## 9. Orden y paralelización

| Ola | Tickets (en paralelo dentro de la ola) |
|---|---|
| 1 | B0 |
| 2 | B1, F0 |
| 3 | B2, B3, F1 |
| 4 | B4, B5, F2*, F3*, F4* |
| 5 | B6, B7, F5* |
| 6 | B8, F6* |
| 7 | D1 + verificación E2E (§10) |

\* Los tickets de frontend pueden empezar contra §7 con datos simulados y conectarse cuando esté su ticket
backend correspondiente.

## 10. Verificación end-to-end (criterio de MVP terminado)

1. Pasan todos los checks de §5. `uv run pytest -m slow` pasa en una máquina con Data/001 y los pesos.
2. Con Redis, el worker, la API y la UI levantados:
   - `curl localhost:8000/api/studies` incluye `001/t0`.
   - En la UI: seleccionar 001/t0 → se ve T1Gd multiplanar con el GTV en rojo → la volumetría coincide con la
     tabla de la sección 2 del notebook (`uv run marimo run cerberus_eda.py`), con una tolerancia de ±0.01 cm³.
   - "Segmentar con MONAI" → el job termina → el overlay se ve alineado con la anatomía y el Dice TC es
     comparable al de la sección 5.4 del notebook (se espera una diferencia pequeña por el remuestreo).
   - Subir `Data/001/t0/1_t0_flair.nii.gz` como paciente `900`, tiempo `t0`, secuencia `flair` → aparece en la lista.
   - Subir un zip DICOM de prueba (un estudio público de TCIA o uno sintético) → aparecen las series con
     sugerencias → confirmar → aparece en la lista; `storage/tmp` queda vacío; `grep -ri "<PatientName>" storage Data/900*` no encuentra nada.

## 11. Riesgos conocidos

- Un DICOM de hospital trae series **no co-registradas**: el remuestreo por affine solo es válido dentro de la
  misma sesión. Por eso se muestra un warning; el registro queda para fase 2.
- Sin `brain_mask` (DICOM nuevo) la calidad de MONAI baja. El MVP solo avisa; HD-BET/SynthStrip quedan para fase 2.
- El GTV no es el "volumen tumoral" (excluye edema). Los textos de la UI deben decir "GTV" y no "tumor".
- Inferencia en CPU: varios minutos. Por eso es un job asíncrono y la UI no debe bloquearse.

## 12. Checkpoints y trazabilidad entre dispositivos

El estado del desarrollo vive en el repo, no en la memoria de una persona ni de una IA:
**[`docs/PROGRESS.md`](PROGRESS.md)** es la única fuente de verdad del avance.

**Al empezar una sesión (cualquier dispositivo o herramienta):**
1. `git checkout main && git pull` y luego `uv sync` (y `npm install` en `frontend/` si existe).
2. Lee `docs/PROGRESS.md`: el tablero de tickets y el último checkpoint (su campo "Siguiente paso").
3. Toma un ticket ⬜ cuyas dependencias (§8/§9) estén ✅. Márcalo 🟡 con tu nombre y herramienta, y haz
   commit + push de ese cambio **antes** de programar. Así nadie más lo toma en otro equipo.

**Al terminar un ticket (checkpoint):**
1. Checks de §5 en verde.
2. Haz merge de la rama del ticket a `main` (PR o fast-forward).
3. En `docs/PROGRESS.md`: marca el ticket ✅ con el commit de merge y la fecha, y agrega una entrada `CP-NNN`
   a la bitácora con: qué se hizo, archivos principales, desviaciones del plan, pendientes y siguiente paso.
4. Commit con mensaje `chore(progress): CP-NNN <ticket>` y push.

**Reglas:**
- La bitácora solo crece hacia abajo. No se reescriben checkpoints viejos; si algo cambió, se escribe uno nuevo.
- Una desviación del plan (firma distinta, archivo extra, contrato ajustado) se anota en el checkpoint **y**
  se corrige en este plan en el mismo commit.
- Si un ticket se bloquea, márcalo ⛔ con el motivo y haz push. El siguiente en tomarlo empieza por ahí.
- Fechas en formato ISO `YYYY-MM-DD`. Hashes de commit cortos (7 caracteres).
