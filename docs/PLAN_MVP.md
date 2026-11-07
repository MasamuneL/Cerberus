# Plan MVP — Cerberus Web (FastAPI + React + Niivue)

## Contexto

Cerberus nació como notebook marimo (`cerberus_eda.py`) para inventariar el dataset CFB-GBM (NIfTI), calcular
volumetría del GTV, segmentar con MONAI SegResNet y mostrar cortes y 3D. La app web ya está implementada
con **FastAPI + arq/Redis** (backend Python) y **React + Vite + TypeScript + Niivue** (frontend), incluida
la entrada **DICOM** mediante conversión a NIfTI.

**Estado de implementación:** MVP y extensiones §13–§16 integrados en `main`: áreas de Brodmann, dominios
funcionales, UX/UI, Docker Compose, autoajuste de recursos y caché HTTP. El tablero y los checkpoints
están en [`PROGRESS.md`](PROGRESS.md), y el estado vivo en [`HANDOFF.md`](HANDOFF.md).
S1/S2 del [QA de seguridad y robustez](QA_2026-10-29.md) están corregidos por A3; el resto sigue pendiente; implementar el alcance
no implica que esos fallos estén resueltos.

**Fase de autenticación en desarrollo:** OIDC con Keycloak para la demo académica (§17), con una evolución
posterior hacia identidad y permisos hospitalarios. A0 incorpora configuración e interfaces y A1 el proveedor;
A2 incorpora login y sesiones; A3 aplica permisos y propiedad a recursos. La UI y aceptación final siguen en A4/A5.

Las secciones §1–§10 describen el MVP original y sus tickets. Los contratos iniciales de disco y API
(§6/§7) se complementan con áreas y `Study.has_areas` en §13, dominios en §14 y recursos/caché en §16.
Para arrancar la app actual, consulta también el [README](../README.md).

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

**Extensiones ya implementadas:** áreas de Brodmann (§13), dominios y UX/UI (§14), Docker Compose (§15),
autoajuste de recursos y caché HTTP (§16).

**Autenticación en desarrollo:** login y sesiones desde A2 (§17); A3 protege catálogo, archivos y trabajos.
La interfaz de acceso requiere A4. La aceptación final corresponde a A5.

**Fuera del alcance implementado:** auth/usuarios, base de datos, Otsu/K-Means en la app, edema FLAIR,
skull-stripping automático, registro entre series, RTSTRUCT (rt-utils), exportar DICOM SEG y Mayavi en la app web.

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
| `CERBERUS_CPU_THREADS` | `auto`; entero positivo para fijar los hilos del worker (§16) |

La configuración de autenticación de A0 figura en §17.2. A2 monta las rutas OIDC y sesiones; la protección de
los recursos existentes se aplica en A3, incluida la revalidación de archivos y la propiedad de jobs/ingestas.

Las variables de Compose para puertos, límites de memoria y carpetas del host se documentan en el
[README, opción Docker](../README.md#opción-rápida-docker-desktop-recomendada-para-usarla).

Comandos (todos desde la raíz):

```bash
uv sync                                                    # deps Python (incluye el paquete en modo editable)
redis-server                                               # terminal 1
uv run python -m cerberus_api.worker              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --reload-dir backend --port 8000  # terminal 3: API (docs en /docs)
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

### Autenticación (modelos A0 y rutas A2)

```jsonc
// AuthConfig: únicamente configuración pública
{ "mode": "off" } // "off" | "oidc"

// AuthSession: respuesta de /api/auth/me
{ "roles": ["reader"], "expires_at": "2026-11-05T12:00:00Z", "csrf_token": "…" }
```

`Role = "reader" | "analyst"`. `AuthSession.roles` no admite listas vacías ni roles desconocidos;
`expires_at` exige una fecha ISO-8601 con zona horaria y `csrf_token` no puede estar vacío.
Los modelos existen en Python y TypeScript; `expires_at` es el vencimiento efectivo, limitado por
inactividad y duración absoluta. Las respuestas de auth llevan `Cache-Control: no-store`.
No contienen issuer, subject, cookie, secreto del cliente ni tokens OIDC. La identidad interna es
`Principal(issuer: str, sub: str, roles: frozenset[Role])`, inmutable y con sus tres campos no vacíos;
se define en `identity.py` y no se publica como respuesta de la API.

| Método y ruta | Respuesta |
|---|---|
| `GET /api/auth/config` | Público, 200 `AuthConfig` |
| `GET /api/auth/login` | 302 al proveedor con PKCE/state/nonce; cookie temporal opaca de 300 s |
| `GET /api/auth/callback` | 303 a `/?auth_event=login` tras consumir transacción y validar OIDC; 400 transacción inválida, 401 token inválido, 403 sin rol |
| `GET /api/auth/me` | 200 `AuthSession`; 401 sin sesión válida |
| `POST /api/auth/logout` | 204 tras invalidar Redis y borrar cookies; 401 sin sesión, 403 sin CSRF/Origin válidos |

En modo `off`, solo `/api/auth/config` responde; las demás rutas de auth devuelven 404. Los fallos del
almacén o proveedor producen 503, sin credenciales ni detalles del error en la respuesta. El callback
descarta `code/state` del scope del servidor para los logs, incluso ante fallos de dependencias; nginx
no escribe errores con la query del callback, también en su variante con barra final.
En navegaciones con `Accept: text/html`, errores de identidad en login/callback y transacciones inválidas
vuelven con 303 a `/?auth_error=forbidden|failed|unavailable`; estos códigos fijos no contienen identidad,
code ni state. El callback correcto vuelve a `/?auth_event=login`; la UI consume/borra esa señal fija y
notifica el cambio de sesión a otras pestañas sin identidad ni tokens. Abrir una pestaña normal no emite
un cambio ni cancela trabajo de otras pestañas. Las solicitudes JSON conservan los estados 400/401/403/503 descritos arriba. A4 mostrará
el mensaje correspondiente; el estado de auth del navegador no concede permisos en la API.
Los recursos de estudio, archivos y `/api/system` requieren sesión OIDC (401 sin ella); las mutaciones y
jobs/subidas requieren analista (403 para lector). Jobs e ingestas ajenos o sin propietario responden 404.
Todas las mutaciones OIDC requieren CSRF y Origin autorizado. En `off` requieren `X-Cerberus: 1` y, si
incluyen Origin, uno autorizado. Host se valida en ambos modos. JSON autenticado usa `no-store` y NIfTI
`private, no-cache`, con permisos antes del body/I/O y ETag/304. Los modelos JSON anteriores se conservan.
Los recursos autenticados OIDC añaden `X-Cerberus-Session-Expires-At`, milisegundos Unix del vencimiento
inactividad/absoluto calculado por Redis para esa petición, también en GET/HEAD/206/304. No aparece en
salud/config ni rechazos previos a autenticar. El cliente aplica ese límite solo a su generación de sesión
vigente para avisar/caducar sin sondeos de renovación automática.

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

El [QA del 2026-10-29](QA_2026-10-29.md) amplía esta lista con fallos reproducidos y un plan de corrección
por olas aún pendiente. Incluye metadatos personales conservados al convertir DICOM, limpieza temporal
incompleta ante fallos, CSRF, DNS rebinding y subidas NIfTI que agotan memoria. La ingesta no garantiza
anonimización completa; el aviso original del formulario descrito en F6 sigue pendiente de corregir.

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

**Handoff:** `docs/HANDOFF.md` guarda el estado vivo (trabajo en curso, ramas `wip/`, lecciones aprendidas y
arranque rápido) para que otra herramienta (Codex, etc.) continúe sin contexto previo. Se actualiza en cada checkpoint.

**Reglas:**
- La bitácora solo crece hacia abajo. No se reescriben checkpoints viejos; si algo cambió, se escribe uno nuevo.
- Una desviación del plan (firma distinta, archivo extra, contrato ajustado) se anota en el checkpoint **y**
  se corrige en este plan en el mismo commit.
- Si un ticket se bloquea, márcalo ⛔ con el motivo y haz push. El siguiente en tomarlo empieza por ahí.
- Fechas en formato ISO `YYYY-MM-DD`. Hashes de commit cortos (7 caracteres).

## 13. Fase 2 · Áreas de Brodmann y funciones afectadas

**Origen:** `cerberus_eda.py:1048` ("Registro a MNI + atlas … para reportar áreas de Brodmann afectadas"). Quedó
fuera del MVP por omisión y se recupera aquí (decisión del 2026-10-29).

**Objetivo:** para un estudio con GTV, estimar qué áreas de Brodmann y estructuras subcorticales toca o rodea el
tumor, qué funciones se asocian a ellas y mostrarlas en el visor como overlay con opacidad ajustable.

**Decisiones fijas**

| Tema | Decisión |
|---|---|
| Atlas | Talairach, nivel `ba`, vía `nilearn.datasets.fetch_atlas_talairach("ba", data_dir=models_dir/"atlas")`: 71 regiones (BA1–47 + estructuras subcorticales), 1 mm, espacio MNI |
| Plantilla | `nilearn.datasets.load_mni152_template(resolution=1)` (+ `load_mni152_brain_mask`) |
| Registro | ANTsPy (`antspyx`): paciente → MNI con `type_of_transform="SyN"`; GTV dilatado 5 mm excluido del costo (`moving_mask`); el atlas vuelve al paciente con `invtransforms` + `interpolator="genericLabel"` |
| Hemisferio | Se separa en MNI por la coordenada x del mundo (RAS: x<0 izquierdo). Valor en `brodmann.nii.gz` = índice del atlas (izquierdo) o índice+100 (derecho); 0 = fondo; uint8 |
| Grid de salida | El de la secuencia de referencia del visor (t1gd si existe), para que el overlay coincida con el GTV nativo |
| Funciones | Base curada `backend/cerberus_api/data/area_functions.json` (español, con fuentes), con funciones distintas por hemisferio cuando aplica (ej. BA44 izq. = Broca) |
| Margen | Se reportan las áreas solapadas con el GTV y las que estén a ≤ 10 mm |
| Aviso | Siempre visible en la UI: estimación educativa basada en atlas; no sustituye fMRI, tractografía ni mapeo cortical intraoperatorio; con tumores grandes el registro pierde precisión |

**Contrato (ya en el código, commit del CP-015):** `Study.has_areas`; `AreaLabel`, `AffectedArea`, `AreasResult` en
`schemas.py` / `types.ts`; `SERVABLE_DERIVED` incluye `brodmann`; `client.ts` tiene `startAreaMapping` y `getAreas`.

```
storage/results/<p>/<t>/brodmann.nii.gz   # mapa de etiquetas en el grid de la referencia
storage/results/<p>/<t>/brodmann.json     # AreasResult
storage/results/<p>/<t>/mni/              # transformaciones ANTs en caché
```

| Método y ruta | Respuesta |
|---|---|
| `POST /api/studies/{p}/{t}/areas` | 202 `JobCreated` · 404 sin estudio · 422 sin GTV o sin secuencia T1 · 503 sin Redis |
| `GET /api/studies/{p}/{t}/areas` | `AreasResult` · 404 |
| `GET /api/studies/{p}/{t}/files/brodmann.nii.gz` | mapa de etiquetas |

### Tickets

**B9 · atlas + registro** — `backend/cerberus_api/atlas.py`
- `fetch_atlas(models_dir) -> (Nifti1Image, list[str])` y `fetch_template(models_dir)`, con caché en `models/atlas` (la red
  solo se usa la primera vez).
- `map_atlas(study_files, out_dir, models_dir) -> AtlasMapping` (dataclass: `label_path`, `entries:
  list[tuple[int, str, Hemisphere]]`, `reference_sequence`, `registration` (texto), `warnings`). La imagen móvil es la T1
  sin contraste (t1eg → t1tse → t1gd), enmascarada con `brain_mask` si existe. La transformación se guarda en
  `out_dir/mni/` y se reutiliza. Al final se verifica que el affine de salida sea igual al de la referencia.
- Warnings en español: sin `brain_mask`, solo T1 con contraste, GTV grande (> 10 % del cerebro).
- Tests rápidos sin red ni ANTs (codificación de hemisferios con un atlas sintético) + 1 `slow` real sobre 001/t0.

**B10 · base de funciones** — `backend/cerberus_api/data/area_functions.json` + `area_kb.py`
- Una entrada por cada uno de los 71 nombres del atlas: `name_es`, `kind`, `functions` y, opcionalmente,
  `functions_left` / `functions_right`, `eloquent`, `sources`.
- `load_area_kb()` (cacheado, vía `importlib.resources`) y `functions_for(name, hemisphere)`.
- Tests: cubre los 71 nombres (lista fija en el test); campos válidos; BA44/45 izquierda contiene el lenguaje.

**B11 · reporte + job + API** — `backend/cerberus_api/areas.py`, `worker.map_areas`, rutas en `studies.py`
- `compute_area_report(...)`: solapamiento con el GTV (y con el WT de `monai_seg` si existe, remuestreado con
  orden 0), % del área, cm³ y distancia mínima con EDT en mm. Orden: primero las solapadas y luego las cercanas.
- `run_area_mapping(study_files, out_dir, models_dir) -> AreasResult` escribe `brodmann.json`.
- Tests rápidos con `map_atlas` falso; 1 `slow` real.

**F7 · panel de áreas + overlay** — `components/AreasPanel.tsx`, `Viewer.tsx`, `App.tsx`
- Botón "Mapear áreas afectadas" → job (`useJob`) → tabla: área, hemisferio, % del área en el GTV, cm³,
  distancia, funciones (chips) y badge "Elocuente". Secciones "Afectadas" y "Cercanas (≤ 10 mm)", más warnings y
  el aviso obligatorio.
- Viewer: toggle "Áreas de Brodmann" (si `has_areas`), slider de opacidad propio (0.35 por defecto), modo "Solo
  afectadas / Todas" (alpha 0 para las etiquetas no reportadas) y LUT de etiquetas con nombres (`ColorMap.labels`).
  Al hacer clic en una fila de la tabla se enfoca esa área en el visor.

### Orden

| Ola | Tickets |
|---|---|
| A | B9, B10, F7 (F7 contra el contrato) |
| B | B11 |
| C | E2E: 001/t0 real (áreas coherentes con la localización del GTV) + revisión visual |

## 14. Fase 2b · Mejoras de UX/UI

**Origen:** revisión visual con Playwright (CP-020) + guía de diseño frontend. Decisión del usuario 2026-10-29:
mejoras 1–5 + tipografía + accesibilidad.

**Dirección visual:** "estación de radiología": oscura, densa y precisa; la imagen manda. El usuario debe ver de un
vistazo **dónde está el tumor y qué funciones pone en riesgo**.

**Reglas fijas del sistema visual**
- **Rojo, naranja y amarillo son exclusivos del tumor** (GTV, realce, núcleo, edema). Las áreas usan solo tonos fríos
  (azul, cian, verde, violeta, magenta frío); nunca hues de 0–60° ni de 330–360°.
- Tipografía: IBM Plex Sans (UI) + IBM Plex Mono (todas las cifras, `font-variant-numeric: tabular-nums`), vía
  `@fontsource` (sin CDN).
- Tokens en `:root` de `styles.css`; cada componente nuevo tiene su propio CSS (`viewer.css`, `sidepanel.css`) para
  que los tickets no se pisen.
- Accesibilidad AA: contraste ≥ 4.5:1 en texto, toda acción usable con teclado (`tabIndex`, Enter/Espacio),
  `aria-pressed` en los toggles, leyendas con texto además del color y `prefers-reduced-motion`.

**Contrato (orquestador, CP-021):** `Domain` y `AffectedArea.domains: Domain[]` en `schemas.py` y `types.ts`.

**Semáforo de "Funciones en riesgo"** (por dominio, calculado en el frontend):
- 🔴 **Afectado:** alguna área del dominio se solapa con el GTV y es elocuente.
- 🟠 **Comprometido:** se solapa pero no es elocuente, o es elocuente a ≤ 5 mm.
- 🟡 **En vigilancia:** a ≤ margen (10 mm) sin cumplir lo anterior.
Cada dominio lista sus áreas (nombre corto + hemisferio + % o distancia) y el aviso educativo va debajo.

### Tickets
| ID | Qué | Archivos |
|---|---|---|
| B12 | `domains` / `domains_left` / `domains_right` en `area_functions.json` (71 entradas) + `domains_for(name, hemi)` en `area_kb.py`; `areas.py` llena `AffectedArea.domains`; regenerar `brodmann.json` de 001/t0 y 005/t0 | `backend/cerberus_api/{data/area_functions.json,area_kb.py,areas.py}`, tests |
| F9 | Paleta fría para las áreas; **panel de capas** (ojo, muestra de color, opacidad, modo de áreas) que sustituye los checkboxes; **barra de lectura del cursor** (mm, área bajo el cursor, dentro/fuera del GTV) con `onLocationChange`; atajos `1–5`, `G`, `S`, `A`, `?`; aria en los toggles | `components/Viewer.tsx`, `components/areaColors.ts`, `components/viewer.css` |
| F10 | **Pestañas** en la columna derecha (Volumetría · Segmentación · Áreas · Longitudinal; Áreas por defecto si hay mapa); tarjeta **Funciones en riesgo** arriba de Áreas; filas de la tabla accesibles con teclado; pasos del job (Registro → Atlas → Reporte) | `App.tsx`, `components/{SidePanel,RiskSummary,AreasPanel,VolumetryPanel}.tsx`, `components/sidepanel.css` |
| F11 | Tipografía Plex vía `@fontsource`, tokens y contraste AA en `styles.css`, `StudyList` (GTV cm³ por tiempo, badge "Áreas", navegable con teclado), skeletons de carga | `main.tsx`, `styles.css`, `components/StudyList.tsx`, `package.json` |

Ola única en paralelo (B12, F9, F10, F11) → verificación con Playwright (capturas a 1440×900 y 1280×800) → CP.

## 15. D2 · Docker Compose (Docker Desktop)

**Estado:** implementado e integrado en `main` (CP-031). Las ramas de borrador citadas abajo son históricas.

**Origen:** pedido del usuario; Codex escribió un borrador (respaldado en `wip/d2-docker`, sin build ni pruebas).
**Meta:** `docker compose up -d --build` desde la raíz (o desde Docker Desktop) levanta Cerberus completo en
`http://localhost:8080`, y la segmentación y el mapeo de áreas funcionan dentro de los contenedores.

**Hechos verificados (2026-10-29):** Docker Desktop 29.9 / Compose v5.6, contexto `desktop-linux`, aarch64, 14 CPU,
8 GB de RAM. `antspyx` 0.5.3 y 0.6.3 solo publican wheel **linux x86_64** → el backend usa `platform: linux/amd64`
(Rosetta; `uname -m` = x86_64 verificado). El frontend (nginx) puede ser nativo arm64.

| Servicio | Imagen | Notas |
|---|---|---|
| redis | redis:7.4-alpine (digest) | AOF, healthcheck |
| api | `docker/backend.Dockerfile` (amd64) | uvicorn :8000 interno, healthcheck `/api/health` |
| worker | misma imagen | `python -m cerberus_api.worker` |
| frontend | `docker/frontend.Dockerfile` | nginx :8080 → estáticos + proxy `/api` → api:8000 |

Volúmenes bind: `./Data`, `./storage`, `./models` (pesos MONAI y atlas en caché; si faltan, se descargan dentro).

### Tickets
- **D2a · backend en contenedor:** build amd64, api + worker sanos; dentro de Docker: segmentación de 001/t0
  (Dice TC ≈ 0.857) y mapeo de áreas (BA40 izq. arriba) con tiempos medidos; permisos de los bind mounts
  (UID/GID en macOS), caché de modelos y atlas, límites de memoria razonables para 8 GB.
- **D2b · frontend en contenedor:** build de nginx, proxy `/api` (incluye subidas grandes: `client_max_body_size`
  ≥ `CERBERUS_MAX_UPLOAD_MB`), fallback SPA, cabeceras, `tools/e2e/verify-docker.mjs` en verde y capturas revisadas.
- **D2c · documentación:** README (sección Docker: requisitos de Docker Desktop, RAM recomendada, primer build,
  `docker compose up -d --build`, logs, parar y limpiar), HANDOFF y PROGRESS.

## 16. D2d/D2e · Caché de volúmenes y autoajuste de recursos

**Estado:** implementado e integrado en `main` (CP-034); sin `proxy_cache` en nginx.

**Origen:** preguntas del usuario (2026-10-29): ¿la caché cerca del front? y ¿detectar la configuración óptima de cada
computadora?

**Decisiones**
- **Redis guarda la cola de jobs y el reporte de recursos del worker**; no almacena volúmenes.
  La caché de volúmenes está en el **navegador**: los NIfTI
  (~75 MB) se revalidan con `ETag` / `Last-Modified` → **304**, con `Cache-Control: no-cache` (siempre revalida, nunca
  sirve una versión vieja). Los derivados ya llevan `?v=`. **No** se usa `proxy_cache` en nginx: para un solo usuario
  local no aporta y ocuparía RAM (tmpfs de `/tmp` en un rootfs de solo lectura).
- **Autoajuste:** `CERBERUS_CPU_THREADS=auto` (default). El worker detecta al arrancar, **antes de importar torch y
  ANTs**:
  - CPUs = cuota cgroup v2 (`/sys/fs/cgroup/cpu.max`) → `os.sched_getaffinity` → `os.cpu_count()`;
  - memoria = `memory.max` del cgroup → `/proc/meminfo` → `sysctl hw.memsize` en macOS;
  - dispositivo = cuda → mps → cpu.
  - **hilos = max(1, min(floor(CPUs) − 1, 8))**; un entero positivo en la variable manda. Se aplica a `OMP_NUM_THREADS`,
    `MKL_NUM_THREADS`, `ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS` y `torch.set_num_threads`.
  - Warning si la memoria es < 5 GB (pico medido del worker: 4.2 GiB) o si la plataforma es x86_64 emulada.
- El worker publica su `SystemInfo` en Redis (`cerberus:system:worker`) al arrancar; `GET /api/system` lo devuelve
  o, si no hay, calcula el de la API con `source="api"` y un warning.

**Contrato (orquestador, CP-032):** `SystemInfo` en `schemas.py` / `types.ts`; `getSystem()` en `client.ts`.

`GET /api/system` devuelve `source` (`worker` o `api`), `reported_at`, `in_container`, `platform`,
`cpus_available`, `threads`, `threads_source` (`auto` o `env`), `memory_gb` (puede ser `null`),
`device` (`cuda`, `mps` o `cpu`) y `warnings`. Es información detectada al publicar el reporte, no un
monitor de utilización en tiempo real; el QA registra la ausencia de TTL del reporte del worker (B12).

Las peticiones condicionales a archivos de estudios admiten `If-None-Match` y, en su ausencia,
`If-Modified-Since`; una coincidencia devuelve 304 sin cuerpo. Esto también aplica a `HEAD`.
La caché depende del navegador: CP-034 observó 304 en GTV/MONAI/Brodmann y 200 en T1Gd de 75 MB en
Chrome headless, aunque curl obtuvo 304 para ese archivo. No se garantiza una segunda carga sin descarga
para todos los tamaños de volumen. Las duraciones mostradas en la UI son estimaciones.

| Ticket | Qué | Archivos |
|---|---|---|
| D2e-back | `runtime.py` (detección + aplicación), hook de arranque del worker, `GET /api/system`, `CERBERUS_CPU_THREADS=auto` en compose; 304 condicional (`If-None-Match` / `If-Modified-Since`) + `Cache-Control: no-cache` en `/files/*.nii.gz`; tests con cgroup simulado; prueba en Docker con `--cpus 2 --memory 4g` | `backend/cerberus_api/{runtime.py,worker.py,routers/system.py,routers/studies.py,main.py}`, `compose.yaml`, tests |
| D2e-front | Indicador de recursos en la UI (panel de Segmentación y de Áreas: "CPU · 8 hilos · 6 GB", warnings), tiempo estimado ajustado al dispositivo; verificar en Docker que una segunda carga del estudio da 304 (nginx deja pasar `If-None-Match`/`ETag`) | `frontend/src/components/*`, `docker/nginx.conf` (solo si hace falta), `tools/e2e/*` |

## 17. Autenticación para demo académica · OIDC + Keycloak

**Estado:** A0–A3 integrados; A4/A5 pendientes. El usuario pidió incorporar esta fase
el 2026-11-03 y continuar su desarrollo el 2026-11-05.
El alcance inmediato es una demo académica open source con datos públicos anonimizados o sintéticos;
la visión posterior es una instalación hospitalaria. Este apartado no declara preparación para uso clínico.
Los valores y contratos que siguen son decisiones de esta planificación; entrarán en vigor con sus tickets.

### 17.1. Enfoque y alcance

Se consideraron un login propio, un servicio de identidad administrado y OIDC con un proveedor configurable.
Se adopta **OIDC + Keycloak autohospedado como proveedor incluido para la demo**: evita implementar contraseñas,
MFA y recuperación de cuentas en Cerberus y permite sustituir el proveedor por uno institucional más adelante.
El costo es operar y actualizar un servicio adicional. Keycloak es open source bajo Apache 2.0.

**Incluye:** inicio de sesión, cierre de sesión local, expiración, dos roles de aplicación, protección de API
y archivos, propiedad de jobs/subidas en curso, configuración reproducible de Keycloak y pruebas de acceso.
Las cuentas se crean desde la consola de Keycloak; el registro público queda desactivado.

**Fuera de esta entrega:** registro propio, recuperación de contraseñas dentro de Cerberus, MFA obligatorio,
federación hospitalaria, permisos clínicos por paciente/estudio, auditoría clínica, alta disponibilidad y
certificación normativa. La configuración de demo no se publica en internet ni usa datos clínicos reales.
El rol administrativo de Keycloak no concede por sí mismo permisos dentro de Cerberus.

### 17.2. Arquitectura y despliegue previstos

- FastAPI actúa como cliente OIDC confidencial mediante **Authorization Code + PKCE S256**, `state` y `nonce`.
  Usar Authlib; verificar las APIs de la versión que se instale. No implementar criptografía ni validar JWT a mano.
  Validar firma, algoritmo permitido, `iss`, `aud`, `exp`, `nonce` y `azp` cuando corresponda antes de crear la sesión.
- El navegador solo conserva un identificador opaco en cookie `HttpOnly`, `SameSite=Lax`, `Path=/` y sin `Domain`.
  No se guardan tokens OIDC en `localStorage`, `sessionStorage`, URLs de la app ni cookies legibles por JavaScript.
  Transacciones OIDC y sesiones viven en Redis, bajo claves `cerberus:auth:*`, separadas de arq.
- Identidad interna estable: pareja **(`issuer`, `sub`)**, nunca correo o nombre de usuario como clave de acceso.
  Los roles `reader` y `analyst` se leen del claim validado `cerberus_roles` (lista de cadenas) del ID Token.
  Roles desconocidos se ignoran; una identidad sin ningún rol admitido no obtiene acceso. El realm de demo
  configura el mapper correspondiente; un proveedor institucional podrá adaptar su mapeo sin cambiar la identidad.
- Sesión: identificador aleatorio de al menos 32 bytes, renovación del identificador al autenticar, caducidad
  por inactividad de **30 minutos** y absoluta de **60 minutos**. Transacción de login de un solo uso, TTL **5 minutos**,
  ligada al navegador que la inició; su cookie temporal tampoco contiene `state`, `nonce` ni `code_verifier` en claro.
  Los roles se renuevan con el siguiente login; no se promete revocación institucional instantánea en esta demo.
- Logout invalida la sesión en Redis y borra la cookie. Es cierre de sesión de Cerberus; no promete cerrar
  las sesiones de otras aplicaciones del proveedor. Redis caído produce 503 en operaciones que necesitan sesión;
  no hay acceso anónimo de respaldo. Un fallo de Keycloak impide nuevos logins, sin convertir sesiones en anónimas.
- Añadir `compose.auth.yaml` como overlay explícito: UI de Cerberus en **8080**, Keycloak en **8081**, ambos
  publicados solo en `127.0.0.1`. El arranque objetivo será
  `docker compose --env-file .env.auth -f compose.yaml -f compose.auth.yaml up -d --build`, tras ejecutar
  `uv run python tools/auth/bootstrap.py`. A1 incluye el proveedor; A2 añade sesiones y A3 protege recursos.
  La configuración base sin overlay mantiene el modo local actual; la demo con overlay exige autenticación.
- El overlay incluye PostgreSQL privado para Keycloak y volúmenes persistentes. PostgreSQL no almacena imágenes
  ni sustituye el catálogo en disco de Cerberus. Registrar realm `cerberus`, cliente `cerberus-web`, roles y
  redirect URIs exactas; no usar comodines, credenciales versionadas ni el realm `master` para la aplicación.
  El bootstrap obtiene secretos del entorno y es repetible sin sobrescribir cuentas ni resetear contraseñas.
- Resolver explícitamente el acceso al proveedor desde navegador y contenedores: issuer público de demo
  `http://localhost:8081/realms/cerberus`; backchannel Docker `http://keycloak:8080/realms/cerberus` para
  token/JWKS. Comprobar metadata y transporte sin cambiar el issuer validado ni desactivar validaciones.
  `localhost` dentro de `api` no apunta a Keycloak. En ejecución nativa, el backchannel puede coincidir con el issuer.
- Cookie `Secure` y HTTPS obligatorios fuera de la demo HTTP en loopback. El uso de HTTP y `start-dev`
  queda limitado a esa demo. No se envían imágenes, nombres de pacientes ni identificadores DICOM al proveedor.

**Configuración disponible en `Settings` desde A0** (su conexión con Compose pertenece a A1):

| Variable | Valor o regla |
|---|---|
| `CERBERUS_AUTH_MODE` | `off` en el modo local heredado; el overlay fija `oidc`; ningún fallback automático |
| `CERBERUS_APP_ORIGIN` | Default `http://localhost:5173`; A1 fijará `http://localhost:8080` en Docker; origen exacto sin ruta ni barra final |
| `CERBERUS_OIDC_ISSUER_URL` | Obligatorio en modo `oidc`; issuer público exacto del proveedor |
| `CERBERUS_OIDC_BACKCHANNEL_URL` | Base interna confiable del mismo realm; si se omite, usa el issuer |
| `CERBERUS_OIDC_CLIENT_ID` | Default `cerberus-web`; no vacío en modo `oidc` |
| `CERBERUS_OIDC_CLIENT_SECRET` | Obligatorio en modo `oidc`; solo backend y bootstrap, nunca frontend ni Git |
| `CERBERUS_AUTH_COOKIE_SECURE` | `true`; `false` únicamente con origen público HTTP de loopback |
| `CERBERUS_AUTH_IDLE_TIMEOUT_SECONDS` | `1800` |
| `CERBERUS_AUTH_ABSOLUTE_TIMEOUT_SECONDS` | `3600`; ambos timeouts positivos, absoluto no menor que inactividad |
| `CERBERUS_KEYCLOAK_HTTP_PORT` | `8081`, variable del overlay A1, no de `Settings` |
| `CERBERUS_AUTH_DB_PASSWORD` | Secreto local obligatorio de PostgreSQL, solo overlay/bootstrap |
| `CERBERUS_KEYCLOAK_ADMIN_PASSWORD` | Secreto local obligatorio del administrador, solo Keycloak/bootstrap |
| `CERBERUS_KEYCLOAK_ADMIN_USERNAME` | `cerberus-admin`, solo overlay |

Las URLs requieren HTTP(S), host y puerto válido; no admiten credenciales, espacios, query ni fragmento.
Origen e issuer públicos requieren HTTPS salvo HTTP con `localhost` exacto o IP canónica de loopback;
no se resuelven nombres por DNS para conceder esta excepción. `AUTH_COOKIE_SECURE=false` solo se admite
con origen HTTP de loopback. El backchannel admite HTTP interno explícito y nunca sustituye el issuer
validado; omitirlo conserva exactamente la URL del issuer, incluida su barra final si existe.
En modo `oidc`, se exige issuer, cliente y secreto no vacíos, y CORS rechaza comodines. El secreto usa
`SecretStr`; su representación y serialización lo ocultan, y los mensajes de validación omiten entradas.
El modo `off` no exige proveedor ni secreto y sigue siendo el default. Estas validaciones son locales,
sin discovery ni conexiones a Keycloak/Redis al construir `Settings`. En A2, login/callback consultan
metadata y JWKS por el backchannel; solo se admite firma RS256 y autenticación confidencial `client_secret_basic`.
Authlib 1.9.4 usa HTTPX2 en esta instalación: se declaran ambos junto a joserfc en principal/runtime;
fakeredis con Lua queda solo en dev para probar las operaciones Redis sin red.

### 17.3. Permisos y recursos

| Recurso u operación en modo OIDC | Sin sesión | Lector (`reader`) | Analista (`analyst`, incluye lectura) |
|---|---|---|---|
| Salud mínima y entrada al login | Permitido | Permitido | Permitido |
| Catálogo, detalle, métricas, reportes y `/api/system` | 401 | Permitido | Permitido |
| NIfTI originales, GTV, MONAI y Brodmann; GET y HEAD | 401 | Permitido | Permitido |
| Subir NIfTI/ZIP, segmentar y mapear áreas | 401 | 403 | Permitido con protección CSRF |
| Estado de jobs y manifest/preview/confirm/delete de ingesta | 401 | 403 | Solo recursos propios; ajenos o sin propietario: 404 |

- Todos los estudios anonimizados de la demo forman un **catálogo compartido** entre usuarios con rol admitido.
  No se presenta este modelo como aislamiento entre pacientes. Jobs y subidas en curso sí quedan ligados
  a (`issuer`, `sub`); su propiedad no depende de que siga viva la sesión que los creó.
- La propiedad se registra en Redis bajo `cerberus:auth:owners:*` antes de que el recurso pueda consultarse.
  Se conserva mientras exista el recurso y se limpia al descartarlo o expirar su resultado. Metadata ausente
  implica denegación; no se adoptan automáticamente ingestas/jobs previos a habilitar auth. La pérdida de Redis
  puede volver inaccesibles esos recursos: se documenta y se proporciona limpieza administrativa, sin abrir acceso.
- FastAPI verifica sesión y permisos **antes** de leer archivos, responder 304, escribir o encolar trabajos.
  No basta ocultar botones. Las rutas `/api/auth/*` y salud se exceptúan según la tabla siguiente;
  Swagger, ReDoc y OpenAPI se deshabilitan en el modo OIDC de demo para evitar rutas sin protección.
- Todas las mutaciones de sesión autenticada, incluido logout, requieren token sincronizado en
  `X-CSRF-Token` y `Origin` perteneciente a la lista explícita de orígenes de la app; rechazo 403 si falta
  o no coincide. No se permite CORS con `*` y credenciales. El callback se protege con la transacción OIDC,
  no con una excepción genérica a la protección de métodos mutantes. Validar también `Host` y proxy confiable.
- Respuestas de sesión y JSON autenticado: `Cache-Control: no-store`. Volúmenes: `private, no-cache`,
  con autenticación previa a la revalidación. Logout no garantiza borrar archivos descargados o cachés previas;
  la política hospitalaria de retención en clientes se definirá antes de usar datos reales.

### 17.4. Modelos y endpoints de autenticación

Los modelos `AuthConfig`, `AuthSession`, `AuthMode` y `Role` ya están reflejados en `schemas.py`,
`frontend/src/api/types.ts` y §7 desde A0. `Principal` es interno. A2 implementa los endpoints siguientes;
el resto de API y archivos adquiere protección en A3, y la UI de acceso en A4.

| Método y ruta | Respuesta |
|---|---|
| `GET /api/auth/config` | Público, 200 `AuthConfig = {"mode":"off"\|"oidc"}`; sin secretos |
| `GET /api/auth/login` | 302 al proveedor; callback y regreso a `/` fijados por configuración, sin `return_to` arbitrario |
| `GET /api/auth/callback` | Consume code/state; valida OIDC, crea cookie y devuelve 303 a `/?auth_event=login`; error genérico 400/401, o 403 sin rol |
| `GET /api/auth/me` | 200 `AuthSession = {"roles":["reader"\|"analyst"],"expires_at":"ISO-8601","csrf_token":"…"}`; 401 sin sesión válida |
| `POST /api/auth/logout` | 204 tras invalidar sesión; requiere sesión y CSRF |

Con `AUTH_MODE=off`, `/auth/config` informa `off` y el resto de rutas de autenticación devuelve 404.
Nuevas interfaces compartidas: `Role = Literal["reader", "analyst"]` y
`Principal(issuer: str, sub: str, roles: frozenset[Role])`. El modo local sin auth no fabrica una identidad OIDC.
Una sesión activa puede continuar hasta su caducidad si Keycloak no responde; los nuevos logins devuelven 503.
No se conservan refresh tokens ni se implementa renovación silenciosa en la demo.

### 17.5. Tickets y orden de ejecución

Cada ticket sigue §12: rama, pruebas rápidas sin red, revisión y checkpoint. Los nombres de archivos nuevos
indican destinos previstos; las firmas de librerías se verificarán en su código instalado antes de implementarlas.

| ID | Entrega y archivos principales | Dependencias |
|---|---|---|
| A0 · contratos y configuración | `config.py`, nuevo `identity.py`, `schemas.py`, `frontend/src/api/types.ts`, §7; tipos `Role`, `Principal`, `AuthConfig` y `AuthSession`; tests `test_auth_config.py` | MVP |
| A1 · proveedor reproducible | Nuevo `compose.auth.yaml`, `docker/keycloak/realm.json` sin usuarios/secretos y bootstrap en `tools/auth/`; PostgreSQL privado, realm/roles/cliente y README | A0 |
| A2 · OIDC y sesiones | Nuevos `oidc.py`, `sessions.py`, `routers/auth.py`; `deps.py`, `main.py`, dependencias en `pyproject.toml` y `uv.lock`; tests `test_oidc.py`, `test_sessions.py`, `test_auth_routes.py` | A0, A1 |
| A3 · permisos y propiedad | Nuevo `access.py`; `deps.py`, `main.py`, routers `studies/jobs/uploads`, limpieza en `worker.py`, `docker/nginx.conf`; tests `test_access.py` y ampliación de tests API | A2; coordinar con S1/S2 del QA |
| A4 · UI de acceso | Nuevos `hooks/useAuth.ts`, `components/LoginPanel.tsx`; `App.tsx`, `api/client.ts`, controles en paneles y visor; textos en español, permisos y expiración | A2, A3 |
| A5 · E2E y documentación | Nuevo `tools/e2e/verify-auth.mjs`; runners existentes, README, HANDOFF y PROGRESS; validación con Keycloak real y capturas | A1–A4 y ola P del QA |

**Aceptación por ticket:**

- **A0:** tests de modo off/oidc, secreto requerido, rechazo de origen HTTP no local para cookie insegura y
  timeouts inválidos; paridad Python/TypeScript; no se enciende auth por accidente en los tests existentes.
  Verificar compatibilidad de licencias y versión de Authlib antes de añadirla a los grupos de dependencias.
- **A1:** con secretos locales, el comando del overlay levanta servicios sanos, conserva usuarios al reiniciar,
  permite crear lector/analista sin registro público y registra el callback exacto de la UI en 8080. Se comprueban issuer,
  backchannel y JWKS desde `api`; la documentación distingue 8080, 8081, 5173 y el 8000 interno.
- **A2:** tests con proveedor/transporte y reloj falsos: login válido; `state` o `nonce` incorrectos/ausentes;
  callback repetido, transacción de otro navegador o expirada; firma/issuer/audience/exp inválidos, algoritmo
  no permitido y rotación de claves; sesión fijada, inactividad y caducidad absoluta; logout e indisponibilidad
  de Redis/proveedor. Ningún secreto ni token OIDC aparece en respuestas, logs ni almacenamiento del navegador.
- **A3:** tests parametrizados contra la matriz completa, incluyendo llamadas directas a API, GET/HEAD con
  ETag tras logout y acceso cruzado entre dos analistas a jobs, manifests y previews. Verificar CSRF/Origin,
  Host inválido y que un rechazo no crea archivos ni encola trabajos. El worker conserva las reglas de privacidad.
- **A4:** estados de carga, anónimo, lector, analista, sin permisos y sesión expirada; al recibir 401, detener
  polling, abortar descargas y desmontar el visor/limpiar datos visibles. 403 se muestra como falta de permiso,
  no como sesión caducada. El modo off conserva el flujo local; login, logout y avisos se operan con teclado.
  La ampliación autorizada el 2026-11-07 añade criterios explícitos:
  - Un 401 de NIfTI también retira el visor y aborta descargas pendientes; ningún cargador evita el cliente común.
  - Tras rotar sesión en otra pestaña, logout recupera el CSRF vigente y ofrece un reintento acotado; 403 no se
    presenta como una caída del proveedor. Login/logout/cambio de sesión se sincronizan sin transmitir tokens.
  - Configuración, comprobación de sesión y logout tienen un límite de espera de red y una acción recuperable.
  - Se avisa antes del vencimiento efectivo conocido y solo una acción del usuario comprueba/continúa la sesión;
    no se añade sondeo que renueve indefinidamente la inactividad.
  - Tras reingresar pueden recuperarse trabajos e ingestas propios. Solo se conservan referencias UUID opacas,
    acotadas y con caducidad en sessionStorage; nunca identidad, roles, CSRF, tokens ni datos de estudios.
    La API vuelve a comprobar propietario antes de mostrar o reanudar; referencias ajenas o expiradas se eliminan.
  - «Recordarme» persiste la sesión del proveedor en ese navegador. `prompt=login` sigue exigiendo credenciales;
    no amplía los límites 1800/3600 s de Cerberus. La UI y la documentación explican esa política.
  - Cerberus y el formulario de Keycloak comparten presentación y español, conservando el formulario seguro
    del proveedor. Los cambios de tema/rememberMe se aplican de forma idempotente a realms existentes,
    preservando usuarios, contraseñas, roles y configuración ajena.
- **A5:** navegador real en 8080 con Keycloak en 8081: login lector/analista, prohibiciones, volumen protegido,
  expiración, logout y acceso directo posterior denegado; probar también Vite en 5173 con callback por su proxy.
  Los runners previos reciben sesión cuando auth está activa, nunca un bypass de permisos. Pasan checks §5,
  revisión visual y el QA afectado; se registra evidencia de esta fase sin reutilizar aprobaciones de CP-027/034.

### 17.6. Relación con QA y evolución hospitalaria

La solicitud del 2026-11-05 autoriza continuar los tickets posibles de autenticación, con commit/push frecuentes
y QA antes de cada merge. Se ejecutan por dependencias y en ramas independientes. Las correcciones de la ola P
son dependencias de A5; el resto del QA sigue pendiente y no se incluye implícitamente en cada ticket.
A0/A1 pueden prepararse antes de cerrar la ola P, respetando sus dependencias. S1/S2 se resuelven
coordinadamente con A3 para no duplicar middleware de CSRF/Host; sus guardas deben proteger también
el modo local sin autenticación. La aceptación final de A5 requiere la **ola P** del QA (P1–P3, P5, S1–S3, Q1–Q4),
que sigue pendiente. Añadir login no corrige fugas DICOM, agotamiento de memoria ni carreras de escritura.
El resto de olas R/F/H sigue registrado como pendiente y no desaparece al cerrar esta fase.

Antes de un piloto hospitalario se planificará y validará una fase aparte: identidad institucional por OIDC
(o federación mediante Keycloak), MFA y revocación, permisos por estudio/equipo, auditoría de accesos y
descargas sin PHI en logs, HTTPS y operación de producción con backups, recuperación y política de caché.
Se revisarán también las olas restantes del QA y las obligaciones del hospital. Son requisitos futuros,
no criterios de una demo ni una promesa de cumplimiento clínico o normativo.

**Referencias técnicas** (consultadas 2026-11-03):

- [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html) y [OAuth Security BCP / RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html).
- [Keycloak en Docker](https://www.keycloak.org/getting-started/getting-started-docker), [hostname/backchannel](https://www.keycloak.org/server/hostname) y [licencia](https://github.com/keycloak/keycloak/blob/main/LICENSE.txt).
- [Authlib: clientes web y PKCE](https://docs.authlib.org/en/latest/oauth2/client/web/).
- [OWASP: sesiones](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) y [CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

**Revisión de dependencia para A2 (2026-11-05):** [Authlib 1.9.4 en PyPI](https://pypi.org/project/Authlib/1.9.4/)
declara Python ≥3.10, compatible con Python 3.11 del proyecto, y licencia
[BSD-3-Clause](https://github.com/authlib/authlib/blob/v1.9.4/LICENSE). Permite redistribución abierta o
cerrada conservando avisos y condiciones; al incorporarla se conservarán esos avisos. A0 no instala ni
fija esta dependencia; A2 deberá comprobar versión, avisos de seguridad y APIs instaladas antes de añadirla
a los grupos principal/runtime. No se implementará validación criptográfica propia.

**Verificación de A2 (2026-11-06):** instalados Authlib 1.9.4, HTTPX2 2.15.1 y joserfc 1.8.0, con
BSD-3-Clause declarada en sus metadatos. Se revisaron APIs en el código instalado y el
[changelog de seguridad de Authlib](https://docs.authlib.org/en/stable/upgrades/changelog.html).
Authlib usa HTTPX2 cuando está instalado; el cliente y el transporte de prueba comparten esa API.
`CodeIDToken` valida claims y joserfc verifica firma RS256; se añade la opción de valor de `azp` porque
el validador de Authlib por sí solo omite valores falsos/vacíos. No se implementa criptografía propia.
