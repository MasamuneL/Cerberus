# PROGRESS — Cerberus MVP

Fuente de verdad del avance. Protocolo en [`PLAN_MVP.md` §12](PLAN_MVP.md#12-checkpoints-y-trazabilidad-entre-dispositivos).
Leyenda: ⬜ pendiente · 🟡 en curso · ✅ hecho · ⛔ bloqueado.

## Tablero

| Ticket | Estado | Rama | Commit | Fecha | Responsable / herramienta | Notas |
|---|---|---|---|---|---|---|
| B0 · Bootstrap | ✅ | feat/B0-bootstrap | 31d619a | 2026-10-27 | Vikingo / Claude Code (orquestador) | |
| B1 · config + sequences | ✅ | feat/B1-config-sequences | bad8563 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B2 · catalog | ✅ | feat/B2-catalog | 0f0927f | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B3 · volumetry | ✅ | feat/B3-volumetry | 2d27219 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B4 · API de lectura | ✅ | feat/B4-read-api | 045c005 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B5 · segmentation | ✅ | feat/B5-segmentation | 2dea83a | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B6 · jobs | ✅ | feat/B6-jobs | a528a9b | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B7 · subida NIfTI | ✅ | feat/B7-nifti-upload | e210db6, 8d6f4aa | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B8 · ingesta DICOM | ✅ | feat/B8-dicom-ingest | e5df814 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F0 · Scaffold | ✅ | feat/F0-scaffold | 8aa033a | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F1 · API client | ✅ | feat/F1-api-client | d40323f | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F2 · StudyList | ✅ | feat/F2-F4-ui | 3a80169 | 2026-10-27 | Vikingo / Claude Code (subagente F2-F4) | falta revisión visual WebGL |
| F3 · Viewer | ✅ | feat/F2-F4-ui | 3a80169 | 2026-10-27 | Vikingo / Claude Code (subagente F2-F4) | falta revisión visual WebGL |
| F4 · VolumetryPanel | ✅ | feat/F2-F4-ui | 3a80169 | 2026-10-27 | Vikingo / Claude Code (subagente F2-F4) | falta revisión visual WebGL |
| F5 · SegmentationPanel | ✅ | feat/F5-segmentation-panel | 2c19db0 | 2026-10-27 | Vikingo / Claude Code (subagente) | falta prueba visual |
| F6 · UploadPanel | ✅ | feat/F6-upload-panel | b4c25e3 | 2026-10-27 | Vikingo / Claude Code (subagente) | flujo DICOM se valida en E2E con B8 |
| D1 · README | 🟡 | docs/D1-readme | | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| E2E · Verificación §10 | 🟡 | | | 2026-10-27 | Vikingo / Claude Code (orquestador) | |

## Bitácora de checkpoints

### CP-001 · 2026-10-27 · B0 · `31d619a`
- **Hecho:** el paquete `backend/cerberus_api` se instala en modo editable (hatchling); ruff, pyright y pytest
  configurados en `pyproject.toml`; fixtures `make_nifti`/`make_study` en `backend/tests/conftest.py`, con un cubo
  GTV de 1000 vóxeles (`GTV_SLICE`) y la caja `BRAIN_SLICE`; smoke tests; `.gitignore` con `storage/` y los
  artefactos del frontend.
- **Desviaciones del plan (ya corregidas en PLAN_MVP):**
  - Nuevo `cerberus_api/nifti.py` con `load_nifti()`: pyright tipa `nib.load` como `FileBasedImage`, sin
    `get_fdata`, `affine` ni `get_zooms`. Es obligatorio usarlo en el backend (regla 10 de AGENTS.md).
  - `[tool.pyright] extraPaths = ["backend/tests"]` para poder importar `conftest` (constantes y tipos de las
    fixtures). En ruff, `known-first-party = ["cerberus_api", "conftest"]`.
  - Se agregó el §12 (este protocolo de checkpoints) y `docs/PROGRESS.md`.
- **Checks:** ruff ✅ · format ✅ · pyright 0 errores ✅ · pytest 2 passed ✅.
- **Siguiente paso:** ola 2 en paralelo con subagentes, B1 (config + sequences) y F0 (scaffold del frontend).
  Después, ola 3: B2, B3 y F1.

### CP-002 · 2026-10-27 · F0 · `8aa033a`
- **Hecho:** `frontend/` creado a mano con Vite + React + TS. Layout base con barra lateral (lista de estudios)
  y área principal (visor), ambos placeholders en español. Proxy `/api` → `:8000`. `npm run build` ✅; `npm run dev`
  sirve "Cerberus" en :5173.
- **Versiones fijadas:** react 19.3.1, react-dom 19.3.1, @niivue/niivue 0.69.0, vite 8.3.5,
  @vitejs/plugin-react 6.1.2, typescript 7.0.2, @types/react(-dom) 19.3.0.
- **Desviaciones:** TypeScript 7.0.2 (el plan no fijaba versión; `tsc -b` funciona). Un solo `tsconfig.json`.
  `frontend/*.tsbuildinfo` agregado a `.gitignore`. La API real de Niivue quedó verificada y documentada en el
  ticket F3 del plan.

### CP-003 · 2026-10-27 · B1 · `bad8563`
- **Hecho:** `config.py` (`Settings` con prefijo `CERBERUS_`, rutas relativas a `REPO_ROOT`, propiedades
  `results_dir`, `staging_dir` y `tmp_dir`, `get_settings()` con caché) y `sequences.py` (`SEQ_INFO` y `MRI_SEQS`
  del notebook, `PATIENT_RE`, `TIMEPOINT_RE`, `validate_patient/timepoint/sequence/file_name`).
- **Desviaciones:** las regex llevan `re.ASCII` para rechazar dígitos no ASCII (ej. "٠٠١"); quedó anotado en §6.
  Extras públicos: `REPO_ROOT`, `PATIENT_RE`, `TIMEPOINT_RE`.
- **Checks:** ruff ✅ · format ✅ · pyright 0 ✅ · pytest 78 passed ✅ · `npm run build` ✅.
- **Siguiente paso:** ola 3 en paralelo con subagentes: B2 (catalog), B3 (volumetry) y F1 (API client).
  Después, ola 4: B4, B5, F2, F3 y F4.

### CP-004 · 2026-10-27 · contrato + F1 · `917368e`, `d40323f`
- **Hecho (orquestador, `917368e`):** `backend/cerberus_api/schemas.py` con todos los modelos de §7. Lo escribió
  el orquestador antes de la ola 3 para que B2 y B3 no lo editaran a la vez. Los tickets lo importan y no lo modifican.
- **Hecho (F1, `d40323f`):** `frontend/src/api/types.ts` refleja `schemas.py` campo por campo (snake_case,
  `X | None` → `X | null`). `api/client.ts` tiene `ApiError(status, detail)`, una función por endpoint, `fileUrl`,
  `seriesUrl` e `isUploadCreated`. `hooks/useJob.ts` hace polling con `setTimeout` encadenado (sin solapamiento)
  hasta un estado terminal.
- **Desviaciones:** alias extra `ModelChannel` en `types.ts`. Sin diferencias entre §7 y `schemas.py`.
- **Checks:** `npm run build` ✅ (strict).
- **Siguiente paso:** cerrar B2 y B3 (en curso) y lanzar la ola 4.

### CP-005 · 2026-10-27 · B2 + fix LFS · `0f0927f`, `4470662`
- **Hecho (B2):** `catalog.py` con `list_studies(data_dir, results_dir)`, `get_study(...)` (volúmenes leídos solo
  del header) y `sequence_path(...)`. Valida paciente, tiempo, secuencia y que el prefijo y el tiempo del archivo
  coincidan con sus carpetas; la basura se ignora. 12 tests.
- **Desviaciones (B2):** `list_studies` recibe también `results_dir` (lo necesita `has_segmentation`). La regex usa
  `fullmatch` + `re.ASCII` + `t\d+`.
- **Fix (`4470662`):** la regla LFS `*.ts` (pensada para pesos TorchScript) metía los archivos TypeScript del
  frontend en Git LFS. Ahora es `models/**/*.ts` y los archivos se renormalizaron a blobs normales. Si clonaste
  antes de este commit: `git pull && git lfs pull`.
- **Incidente:** el subagente de B3 se cortó por un error transitorio de la API; se retomó con su contexto.
- **Checks:** catalog: ruff ✅ · pyright ✅ · 12 passed ✅.
- **Siguiente paso:** B3 (retomado), B5 (segmentation) y F2+F3+F4 (un solo subagente, porque comparten `App.tsx`)
  en paralelo. Después: B4 → conectar el frontend → ola 5.

### CP-006 · 2026-10-27 · B3 · `2d27219`
- **Hecho:** `volumetry.py` con `gtv_volumetry`, `rano_category` y `longitudinal`, portados de
  `cerberus_eda.py:209-235` y `:300-312` con las mismas fórmulas y el mismo redondeo. 18 tests.
- **Validación con datos reales (001/t0):** GTV 33.14 cm³ · cerebro 1231.3 cm³ · 2.69 % · LR/AP/SI 38/52/52 mm ·
  ABC/2 51.38 cm³ (+55.0 %) · 1 componente · medible RANO. Valores de referencia para la verificación E2E (§10).
- **Desviaciones:** un GTV vacío lanza `ValueError` (el notebook dividía entre cero). `ndi.label` se desempaqueta
  con un `isinstance` para que pyright quede en 0 errores. Si falta la carpeta del paciente, `longitudinal` devuelve `[]`.
- **Siguiente paso:** B4 (API de lectura) en paralelo con B5 y F2-F4, que siguen en curso.

### CP-007 · 2026-10-27 · B5 + B4 · `2dea83a`, `045c005`
- **Hecho (B5):** `segmentation.py` con `run_segmentation(study_files, out_dir, models_dir, predictor=None)`: grid de
  1 mm, normalización numpy equivalente a MONAI, predictor inyectable (por defecto el bundle BraTS SegResNet) y
  salida `monai_seg.nii.gz` + `.json`. 5 tests rápidos y 1 `slow`.
- **Validación con el modelo real (001/t0, mps, 17.7 s):** canales T1c←t1gd, T1←t1eg, T2←t2star, FLAIR←flair, sin
  warnings. WT 53.51 · TC 31.01 · ET 20.99 cm³. **Dice vs GTV: TC 0.857, WT 0.718**. TC dentro del rango
  interobservador 0.72–0.88. Referencia para el E2E.
- **Hecho (B4):** `main.py` (`create_app`, CORS, `/api/health`), `deps.py` (`settings_dep`, `SettingsDep`) y
  `routers/studies.py` con los 5 GET de §7. 20 tests. Smoke test real: 8 estudios, volumetría 001/t0 = 33.14 cm³,
  descarga de t1gd de 74 634 926 bytes y path traversal → 404.
- **Desviaciones:** (B5) imports desde submódulos de monai por pyright; tuplas en `blocks_down/up`. (B4) la ruta de
  archivos acepta GET y HEAD; `longitudinal` devuelve 422 si algún tiempo tiene el GTV vacío; dependencias con
  `Annotated` (`SettingsDep`).
- **Checks:** ruff ✅ · format ✅ · pyright 0 ✅ · pytest 133 passed ✅ · slow 1 passed ✅.
- **Siguiente paso:** ola 5: B6 (jobs; dueño de `main.py`) y B7 (subida de NIfTI; su router lo conecta el
  orquestador al hacer merge). F2-F4 siguen en curso y se conectan contra B4 real al cerrar.

### CP-008 · 2026-10-27 · F2 + F3 + F4 · `3a80169`
- **Hecho:** `StudyList.tsx` (agrupada por paciente, con badges GTV y Seg), `Viewer.tsx` (una sola instancia de
  Niivue; secuencia, overlay del GTV con opacidad, overlay `monai_seg` con colormap de etiquetas y fallback `warm`,
  vistas MPR/axial/coronal/sagital/3D, leyenda) y `VolumetryPanel.tsx` (volumetría + tabla RANO longitudinal).
  `App.tsx` conecta lista → detalle → visor + panel. Un solo commit y una sola rama porque los tres editan `App.tsx`.
- **Verificado por HTTP contra la API real a través del proxy de Vite:** 8 estudios, longitudinal 001, descarga
  de t1gd (74 MB, `application/gzip`), módulos servidos.
- **Pendiente:** revisión visual en el navegador (render WebGL de Niivue y colores del mapa de etiquetas). En esta
  sesión no hubo navegador automatizable (falta la extensión de Playwright MCP). Ver §10.
- **Desviaciones:** `StudyList` recibe además `loading` y `error`; `monai_seg` no aparece en el selector de
  secuencias; overlay de segmentación a opacidad 0.6; `showSegmentation` queda en `false` hasta F5.
- **Nota de entorno:** en la máquina del orquestador el puerto 5173 lo ocupa otro proyecto; para probar se usó
  `npx vite --port 5180 --strictPort`.
- **Siguiente paso:** B6 y B7 en curso → F5 (panel de segmentación) → B8 + F6.

### CP-009 · 2026-10-27 · B7 · `e210db6`
- **Hecho:** `routers/uploads.py` con `POST /uploads` (multipart). Escribe en streaming a `storage/tmp` en bloques de
  1 MiB con tope `max_upload_mb` (413), valida un NIfTI 3D (acepta 4D con última dimensión 1) y lo guarda como
  `.nii.gz` en la ruta de §6. Duplicado → 409, `.zip` → 501 hasta B8, otra extensión → 415. `tmp` se limpia
  siempre. 16 tests.
- **Desviaciones:** el router **todavía no está incluido en `main.py`**: B6 es dueño de ese archivo en esta ola y el
  orquestador lo conecta al cerrar B6 (los tests montan el router en su propia app). Los tests tipan la respuesta
  como `Any` por el `TestClient` de Starlette.
- **Checks:** ruff ✅ · pyright 0 ✅ · 16 passed ✅.
- **Siguiente paso:** cerrar B6 → conectar uploads en `main.py` → F5 y B8 en paralelo.

### CP-010 · 2026-10-27 · B6 + conexión de B7 · `a528a9b`, `8d6f4aa`
- **Hecho (B6):** `deps.get_redis` (pool arq lazy; 503 en español si Redis no está), `worker.py`
  (`segment_study` con `asyncio.to_thread`, `ingest_dicom` como stub para B8, `max_jobs=1`, `job_timeout=1800`),
  `routers/jobs.py` (`GET /api/jobs/{id}`) y POST/GET de segmentación en `studies.py`. 21 tests.
- **E2E real por la cola (Redis + worker + API, 001/t0, mps):** 13.2 s; WT 53.51 · TC 31.01 · ET 20.99 cm³;
  **Dice TC 0.857 / WT 0.718**, igual que la llamada directa de CP-007. Redis caído → 503.
- **Hecho (`8d6f4aa`):** el router de uploads se incluyó en `main.py`; sus tests ya usan la app real.
- **Desviaciones (B6):** `conn_retries=1` para fallar rápido (503 en ~2 s); errores de Redis en enqueue/status → 503;
  `enqueue_job` devuelve None → 409; `monai_seg.json` corrupto → 500; resultado expirado → `not_found`. Con Redis
  caído, el POST responde 503 antes que 404.
- **Checks:** ruff ✅ · pyright 0 ✅ · pytest 170 passed ✅.
- **Siguiente paso:** F5 (panel de segmentación) y B8 (ingesta DICOM) en paralelo; después F6.

### CP-011 · 2026-10-27 · F5 · `2c19db0`
- **Hecho:** `SegmentationPanel.tsx`: botón "Segmentar con MONAI" ("Volver a segmentar" si ya hay resultado),
  estados En cola / Procesando (con segundos transcurridos) / Completado / Falló / Job no encontrado, alertas
  con el `detail` de la API (ej. 503 de Redis), y tablas de volúmenes, Dice, canales y warnings con leyenda.
  `App.tsx` refresca la lista y el detalle al completar; `Viewer.tsx` vuelve a encender el overlay en cada nueva
  segmentación.
- **Desviaciones:** `segVersion` solo crece (cache-busting seguro). Si se cambia de estudio con un job en curso,
  el panel deja de seguirlo; el resultado aparece al volver a abrir el estudio.
- **Checks:** `npm run build` ✅. **Pendiente:** prueba visual con Redis + worker (va en el E2E de §10).
- **Siguiente paso:** B8 en curso; F6 se lanza ya contra el contrato §7.

### CP-012 · 2026-10-27 · F6 · `b4c25e3`
- **Hecho:** `UploadPanel.tsx` (modal que se abre con "Subir estudio"): validación de paciente, tiempo y secuencia
  en el cliente; NIfTI → 201 y abre el estudio; ZIP → polling del manifest cada 2 s, tabla de series con un
  select por serie (sugerencia + "Ignorar"), bloqueo por secuencias repetidas, Confirmar y Cancelar (DELETE).
  Aviso de anonimización siempre visible.
- **Desviaciones:** el mensaje de éxito de NIfTI casi no se ve porque el panel se cierra y abre el estudio. Un 404
  del manifest detiene el polling y muestra el error.
- **Checks:** `npm run build` ✅. Construido sobre el contrato §7; el flujo DICOM se valida en el E2E cuando cierre B8.
- **Siguiente paso:** cerrar B8 → E2E §10 → D1 (README).

### CP-013 · 2026-10-27 · B8 · `e5df814`
- **Hecho:** `dicom.py` (`safe_extract` contra zip-slip, symlinks y zip-bomb; `group_series` leyendo solo headers y
  sin datos personales ni UIDs; `suggest_sequence`; `convert_series` con `dcm2niix -z y -b n -i y -f series`),
  `staging.py` (manifest atómico, `upload_id` de 32 hex validado), `worker.ingest_dicom` (borra el tmp y el zip en
  `finally`) y las rutas zip/manifest/preview/confirm/delete de §7. 72 tests en `test_dicom.py` (2 `slow` con
  dcm2niix real).
- **Datos personales:** los tests verifican que el manifest, el header NIfTI y la ausencia de sidecar JSON no
  contengan nombre, ID, fecha de nacimiento, institución, accession, fecha del estudio ni UIDs. El E2E del subagente
  (redis + worker + API aislados) dejó `storage/tmp` vacío y logs sin datos personales.
- **Desviaciones:** (1) se editó `test_jobs.py` (el test del stub pasó a validar un `upload_id` inválido) y en
  `test_uploads.py` un `.zip` inválido ahora da 422; (2) la rama zip resuelve Redis de forma interna
  (`_resolve_redis`) para que subir NIfTI no dependa de Redis; endpoint async + `run_in_threadpool`; (3) `gre` → t2star
  solo si no hay `t1` ("T1 GRE" → t1eg), corregido en §8 B8; palabras completas para la detección de contraste;
  (4) una falla del worker escribe el manifest `failed` con un mensaje genérico en lugar de lanzar la excepción;
  (5) solo acepta y borra zips dentro de `storage/tmp`; (6) una serie no 3D → `converted=False`.
- **Checks:** ruff ✅ · format ✅ · pyright 0 ✅ · pytest 240 passed ✅ · slow DICOM 2 passed ✅.
- **Siguiente paso:** D1 (README, subagente) en paralelo con el E2E §10 completo (orquestador).
