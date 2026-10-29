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
| D1 · README | ✅ | docs/D1-readme | 656b2b1 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| E2E · Verificación §10 | ✅ | main | 656b2b1 | 2026-10-27 | Vikingo / Claude Code (orquestador) | API/flujo ✅; visual ✅ en CP-020 |
| B9 · atlas + registro (§13) | ✅ | feat/B9-atlas-registration | 409bf37 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| B10 · base de funciones (§13) | ✅ | feat/B10-area-kb | dcd2344 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| B11 · reporte + job + API (§13) | ✅ | feat/B11-areas-report | a7371bd | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| F7 · panel de áreas + overlay (§13) | ✅ | feat/F7-areas-ui | b325bf5 | 2026-10-29 | Vikingo / Claude Code (subagente) | falta prueba con backend real |
| E2E · áreas (§13) | ✅ | main | cbca8ad | 2026-10-29 | Vikingo / Claude Code (orquestador) | API/flujo ✅ + visual con Playwright ✅ |
| F8 · ajustes visuales (Playwright) | ✅ | fix/F8-viewer-centering | cbca8ad | 2026-10-29 | Vikingo / Claude Code (subagente + orquestador) | |
| B12 · dominios funcionales (§14) | ✅ | feat/B12-domains | 1088611 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| F9 · capas + paleta + cursor (§14) | ✅ | feature/ux-ui | fad8562, af22c29, d406354 | 2026-10-29 | Vikingo / Claude Code + Codex | Integrado en main: PR #1, bcef409; CP-028 |
| F10 · pestañas + funciones en riesgo (§14) | ✅ | feature/ux-ui | fad8562, d406354 | 2026-10-29 | Vikingo / Claude Code + Codex | Integrado en main: PR #1, bcef409; CP-028 |
| F11 · tipografía + accesibilidad + lista (§14) | ✅ | feat/F11-type-a11y | 5b7b024 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D2a · backend en Docker (§15) | 🟡 | feat/D2-docker-compose | | 2026-10-29 | Vikingo / Claude Code (subagente) | borrador de Codex en wip/d2-docker |
| D2b · frontend en Docker (§15) | 🟡 | feat/D2-docker-compose | | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D2c · docs Docker (§15) | ⬜ | | | | | al final |

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

### CP-014 · 2026-10-27 · D1 + E2E §10 · `656b2b1`
- **Hecho (D1):** README con la sección App web (requisitos, arranque en 4 terminales, arquitectura, funciones,
  tabla de 14 endpoints, variables de entorno), Desarrollo en equipo (AGENTS/PLAN/PROGRESS, checks), Resultados de
  referencia y aviso de privacidad DICOM.
- **E2E §10 con la pila real** (redis-server :6379 + worker arq + API :8000 + Vite :5180, llamadas a través del
  proxy de Vite):
  - 8 estudios; volumetría 001/t0 GTV = 33.14 cm³ ✅; longitudinal 005: t0 76.44 → t1 66.73 (SD) → t2 61.75 (SD) ✅.
  - Segmentación 005/t1 por la cola: completada en 18.1 s; WT 145.89 · TC 55.09 · ET 31.27 cm³; **Dice TC 0.892 /
    WT 0.598**; `monai_seg.nii.gz` servible ✅.
  - Subida NIfTI (flair de 001 como 900/t0) → 201; duplicado → 409 ✅.
  - ZIP DICOM sintético con datos personales falsos (2 series: "AX T1 POST GD" con agente de contraste y "AX FLAIR")
    → 202 → manifest `ready` con sugerencias t1gd y flair → confirm 201 ✅. `storage/tmp` vacío, staging eliminado y
    **ningún dato personal** (nombre, ID, nacimiento, institución, accession, fecha) en `storage/` ni en `Data/901` ✅.
  - Los estudios de prueba 900 y 901 se borraron al terminar.
- **Pendiente humano:** revisión visual en el navegador (render de Niivue, colores del GTV y de las etiquetas,
  panel de segmentación y modal de subida). En esta máquina no hubo navegador automatizable.
- **Siguiente paso:** MVP completo a nivel de API y flujo. Queda la revisión visual y luego la fase 2 (§1 "No incluye").

### CP-015 · 2026-10-29 · arranque de la fase 2: áreas de Brodmann (§13)
- **Contexto:** el usuario preguntó por las áreas de Brodmann (idea de `cerberus_eda.py:1048`), que se había omitido
  del MVP sin dejarla anotada. Decisión: atlas Talairach-Brodmann (nilearn), implementarlo ya como fase 2.
- **Hecho (orquestador):** dependencias `antspyx` 0.5.3 y `nilearn` 0.14.1. Se verificó el atlas: 71 regiones
  (BA1–47 + subcorticales), 141×172×110 a 1 mm en MNI. Contrato §13: `Study.has_areas`, `AreaLabel` /
  `AffectedArea` / `AreasResult` en `schemas.py` y `types.ts`, `brodmann` como archivo derivado servible (el resolver
  ahora es genérico para `SERVABLE_DERIVED`), `startAreaMapping` y `getAreas` en `client.ts`. Se ajustó un test de
  uploads por el campo nuevo.
- **Checks:** ruff ✅ · pyright 0 ✅ · pytest 240 passed ✅ · `npm run build` ✅.
- **Siguiente paso:** ola A en paralelo con subagentes: B9, B10 y F7. Después, B11.

### CP-016 · 2026-10-29 · F7 · `b325bf5`
- **Hecho:** `AreasPanel.tsx` (job de mapeo, tablas "Afectadas por el GTV" y "Cercanas (≤ margen)", chips de funciones,
  badge Elocuente, clic → enfocar área, aviso educativo siempre visible), `areaColors.ts` (paleta determinista; el
  mismo tono para izquierdo y derecho con distinta luminosidad), overlay `brodmann` en `Viewer.tsx` (cargado al final
  para no mover los índices del GTV y la segmentación; opacidad propia 0.35; modos "Solo afectadas" / "Todas" con las
  no reportadas atenuadas; foco), y estado `areas` / `areasVersion` / `focusedLabel` en `App.tsx`.
- **Niivue verificado en el código fuente:** el LUT de etiquetas se indexa por el valor del vóxel (`I`), los
  valores ausentes quedan transparentes, `A` se respeta tal cual (el 0 se agrega explícitamente con alpha 0), y
  `labels` se alinea por posición con `I`, empezando en 0 para que la lectura del cursor coincida.
- **Contrato implícito:** `overlap_gtv_pct` y `overlap_wt_pct` van en **0–100** (B11 debe respetarlo).
- **Checks:** `npm run build` ✅. Pendiente: prueba con el backend real (B9–B11).

### CP-017 · 2026-10-29 · B10 · `dcd2344`
- **Hecho:** `data/area_functions.json` (71 regiones: 42 BA + 29 subcorticales) y `area_kb.py` (`load_area_kb`,
  `area_info`, `functions_for(name, hemisferio)`). 78 tests.
- **Criterios de contenido:** funciones de libro de texto (Kandel 2021, Purves 2018, Strotzer 2009, Haines 2018). El
  flag elocuente sigue a Spetzler-Martin / Sawaya 1998: 13 áreas corticales (1, 2, 3, 4, 6, 17, 22, 39, 40, 41, 42, 44, 45)
  y 20 subcorticales (núcleos talámicos, hipotálamo, subtálamo, núcleo rojo, sustancia negra, dentado, tracto
  óptico, hipocampo). Funciones por hemisferio en BA22, 37, 39, 40, 44, 45 e hipocampo. El orquestador revisó una
  muestra (BA4, 6, 17, 44, 10, 24, 13, hipocampo, amígdala, VPL, BA33).
- **Decisiones discutibles:** BA22 completa es elocuente (el atlas no separa su parte posterior); BA39/40 son
  elocuentes en ambos hemisferios (el flag es por área).
- **Checks:** pyright 0 en sus archivos ✅ · 78 passed ✅. El JSON entra en el wheel sin cambiar pyproject.
- **Siguiente paso:** cerrar B9 (en curso) → B11.

### CP-018 · 2026-10-29 · B9 · `409bf37`
- **Hecho:** `atlas.py`: `fetch_atlas`, `fetch_template`, `split_hemispheres` (izquierdo = índice, derecho =
  índice + 100), `select_sequences` y `map_atlas`. Registro ANTs SyN de t1eg (enmascarada, 1.5 mm) → MNI152 con el GTV
  dilatado 5 mm excluido del costo en todas las etapas. El atlas vuelve al grid nativo de t1gd con `genericLabel` y se
  verifica que el affine sea idéntico al de la referencia. Transformaciones en caché por hash de las entradas.
  13 tests rápidos + 1 slow.
- **Validación real (001/t0):** 16–17 s (registro ~12 s; ~3 s con caché); 142 etiquetas. Centroide del GTV en MNI
  **(−38, −51, 36)**, lóbulo parietal inferior izquierdo. Áreas con más vóxeles del GTV: **BA40 izq., BA7 izq.,
  BA39 izq.**, BA19 izq., BA2 izq. Es coherente con la localización. Dice entre la máscara cerebral registrada y la
  máscara MNI: 0.93.
- **Desviaciones:** la plantilla MNI viene empaquetada con nilearn (sin caché en `models/`); `split_hemispheres`
  acepta `labels`; ANTs multihilo da pequeñas variaciones entre corridas aunque se fije la semilla (BA40 15064 vs
  14576 vóxeles).
- **Checks:** ruff ✅ · pyright 0 ✅ · pytest 331 passed ✅ · slow ✅.
- **Siguiente paso:** B11 (reporte, job y API) y luego el E2E de áreas.

### CP-019 · 2026-10-29 · B11 + E2E de áreas · `a7371bd`
- **Hecho (B11):** `areas.py` (`compute_area_report` con `bincount` + EDT recortada, `run_area_mapping` escribe
  `brodmann.json`), `worker.map_areas` y `POST/GET /api/studies/{p}/{t}/areas` (404/422/503/409/500). 20 tests
  rápidos + 1 slow.
- **001/t0 (slow, solo GTV):** afectadas BA40 izq. 63.0 % (elocuente), BA7 izq. 25.9 %, BA39 izq. 57.6 % (elocuente),
  BA19, ínsula, BA2, BA22, BA5. Cercanas: cuerpo calloso 1.5 mm, BA1 1.7 mm, BA41 2.0 mm, BA4 3.7 mm,
  hipocampo 3.9 mm. Con MONAI, BA40 izq. tumor+edema = 4.25 cm³ / 70.3 %.
- **E2E de la pila completa (Redis + worker + API + Vite :5180, por el proxy):** 005/t0 job completo en 23 s, sin
  warnings, 142 etiquetas. Tumor temporal/insular profundo derecho: BA20 der. 81 %, putamen 37 %, BA21 39 %, cuerpo
  calloso, ínsula, globo pálido lateral, pulvinar (elocuente), BA36, BA41 (elocuente, auditiva primaria). Coherente con
  el GTV de 76 cm³. `has_areas` = true en 001/t0 y 005/t0.
- **Desviaciones:** `run_area_mapping` lee el WT de `out_dir` (3 argumentos, como §13). Los solapamientos < 0.005 cm³
  guardan 4 decimales para que no aparezcan como "0" en la sección de afectadas. Hay 409 si arq no devuelve un job.
- **Nota de interpretación:** el nivel `ba` del atlas Talairach etiqueta corteza gris (y núcleos), no sustancia blanca;
  "% del área" es la fracción de esa corteza etiquetada dentro del GTV. El MONAI WT no es un superconjunto del GTV, así
  que su solapamiento puede ser menor.
- **Checks:** ruff ✅ · pyright 0 ✅ · pytest 351 passed ✅ · slow ✅ · `npm run build` ✅.
- **Pendiente:** revisión visual (overlay de áreas, modos, foco, colores y nombres en la lectura del cursor).

### CP-020 · 2026-10-29 · verificación visual con Playwright + F8 · `cbca8ad`
- **Método:** `playwright-core` 1.64.1 (fuera del repo) con Google Chrome headless y WebGL vía SwiftShader
  (`--use-angle=swiftshader --enable-unsafe-swiftshader`), viewport 1440×900, contra la pila real en :5180. Nota: leer
  píxeles del canvas WebGL con `drawImage` devuelve negro (`preserveDrawingBuffer=false`), así que se revisan
  capturas de pantalla.
- **Funcionaba de entrada:** lista (8), render 2D/3D, overlays GTV y MONAI alineados (005/t0), tablas de volumetría,
  RANO y segmentación, panel de áreas (23 filas, BA40 izq. arriba), aviso educativo, modal de subida.
- **Fallos encontrados → F8:** (1) la mira abría en el centro del volumen y en 001 los cortes no pasaban por el GTV;
  (2) el panel de áreas a 340 px apilaba las funciones y cortaba la columna "% WT"; (3) warning de React por
  `key` en `AreasTable`.
- **Incidente:** el subagente de F8 reportó el centrado como resuelto, pero asignaba mm a `scene.crosshairPos`, que
  es una **fracción** de la escena. Lo corrigió el orquestador: centroide de vóxeles en el orden del archivo → mm con
  `hdr.affine` → `nv.mm2frac` (`vox2frac` no sirve porque usa `dimsRAS`, el volumen reorientado). Ahora la mira queda
  en frac (0.359, 0.333, 0.72) sobre el tumor parietal izquierdo de 001.
- **Verificado tras F8:** GTV (rojo), MONAI (naranja) y áreas de Brodmann (colores) visibles en 2D y 3D; el foco en
  BA40 deja solo BA40 en 3D; las funciones van como chips en una fila propia; botón "Centrar en GTV". La consola solo
  muestra un 404 esperado.
- **Checks:** `npm run build` ✅.

### CP-021 · 2026-10-29 · arranque de §14 (UX/UI)
- **Decisión:** el usuario aprobó las mejoras 1–5 + tipografía + accesibilidad, con dirección "estación de radiología".
- **Hecho (orquestador):** contrato `Domain` + `AffectedArea.domains` (default `[]`, compatible hacia atrás), §14 del
  plan con las reglas del sistema visual (rojo, naranja y amarillo solo para el tumor; áreas en tonos fríos; Plex;
  CSS por componente; AA) y el semáforo de "Funciones en riesgo".
- **Siguiente paso:** B12, F9, F10 y F11 en paralelo → Playwright → CP-022.

### CP-022 · 2026-10-29 · B12 · `1088611`
- **Hecho:** `domains`, `domains_left` y `domains_right` en las 71 entradas de `area_functions.json`; `domains_for()` en
  `area_kb.py`; `areas.py` llena `AffectedArea.domains`. Se regeneró `brodmann.json` de 001/t0 (23 áreas) y 005/t0
  (58 áreas). Lenguaje solo aparece por lateralidad izquierda (BA21, 22, 37, 39, 40, 44, 45, 47). Atención espacial,
  integración multimodal y olfato → "otro". 425 tests.
- **Ejemplo 001/t0:** BA40 izq. [lenguaje, sensitivo], BA39 izq. [lenguaje, otro], BA7 izq. [vision, motor].
- **Incidente de entorno:** la API corría sin `--reload` desde antes del cambio de contrato y su `response_model`
  viejo descartaba `domains`. Se reiniciaron la API (ahora con `--reload --reload-dir backend`) y el worker.
  **Regla:** después de cambiar `schemas.py`, reinicia la API y el worker.
- **Checks:** ruff ✅ · pyright 0 ✅ · pytest 425 passed ✅.

### CP-023 · 2026-10-29 · handoff entre herramientas
- **Pedido del usuario:** dejar checkpoints y handoffs para poder pasar a Codex si se acaba el uso.
- **Hecho:** `docs/HANDOFF.md` (arranque rápido, estado vivo de §14, cómo terminar F9–F11, lecciones aprendidas y
  protocolo); el script de Playwright pasó al repo en `tools/e2e/` (`playwright-core` 1.64.1 fijado, con su propio
  `package.json`; URL configurable con `CERBERUS_UI`); `AGENTS.md` (paso 0 lee HANDOFF, paso 6 lo actualiza, paso 7
  verificación visual) y §12 del plan.
- **Trabajo en curso respaldado:** foto del árbol de F9–F11 en la rama `wip/ux-14` (sin tocar el árbol de trabajo).
- **Siguiente paso:** integrar F9, F10 y F11 cuando terminen → Playwright → CP-024 + actualizar HANDOFF.

### CP-024 · 2026-10-29 · F11 · `5b7b024`
- **Hecho:** IBM Plex Sans/Mono (`@fontsource` 5.3.0) con cifras tabulares; tokens de diseño en `:root` (fondos,
  texto, acento, foco, estados y colores reservados para el tumor, espaciado, radios); anillo `:focus-visible`
  global; `.skeleton`; `prefers-reduced-motion`. `StudyList`: volumen del GTV por tiempo, badge "Áreas", tendencia
  RANO por paciente (↑ +2 % en 003, ↓ −19 % en 005), `aria-current`, flechas/Home/End y skeletons.
- **Contraste AA calculado:** texto 13–16:1, texto atenuado ≥ 6.4:1, acento ≥ 6.2:1, todos los badges ≥ 4.98:1.
- **Desviación:** volumen y tendencia salen de `getLongitudinal` por paciente (5 requests, concurrencia 3, caché)
  en vez de `getVolumetry` por estudio.
- **Integración:** se verificó que compila **aislado sobre main** (worktree temporal) antes del commit; `main` se movió
  sin tocar el árbol de trabajo, donde siguen F9 y F10.
- **Feedback a F9 (en curso):** el panel de capas flotaba sobre el tile coronal y lo tapaba, y "Áreas…" se truncaba
  a 1280 px. Se le pidió que lo saque del canvas o lo haga colapsable.

### CP-025 · 2026-10-29 · recuperación del handoff UX/UI (en curso)
- **Pedido del usuario:** continuar el handoff de Claude, ejecutar o crear QA y subir a `feature/ux-ui`;
  coordinar subagentes y dejar un estado recuperable. No hacer merge a `main`.
- **Hecho:** `git pull` al día; rama creada conservando el árbol de F9/F10. Capas fuera del canvas, paleta fría,
  lectura de cursor, atajos, pestañas y resumen de riesgos recuperados. Revisión paralela de visor y paneles;
  QA separado en `tools/e2e` con `@axe-core/playwright` fijado y lockfile.
- **Checks de entrada:** frontend build correcto; ruff y formato correctos; pyright 0 errores;
  pytest rápido **425 passed, 5 deselected**. Aún no hay aprobación del QA visual actualizado.
- **Hallazgo:** el QA anterior usa checkbox para MONAI y falla con los nuevos botones. Sus chequeos de píxeles
  WebGL tampoco son válidos con `preserveDrawingBuffer=false`; reemplazarlos por asserts y capturas revisadas.
- **Revisión posterior:** se corrigieron opacidades durante cargas, lecturas parciales y atajos con foco en la
  subida. Texto GTV: contraste de 4.42:1 a 6.45:1. Revisión independiente sin bloqueantes; build repetido correcto.
  El QA completo sigue en ejecución y no debe contarse como aprobado todavía.
- **Siguiente paso:** terminar revisión F9/F10 y QA a 1440×900 y 1280×800, revisar capturas, corregir los fallos,
  repetir checks afectados y registrar CP-026 antes del push final a esta rama.

### CP-026 · 2026-10-29 · QA UX/UI y correcciones (en curso)
- **Hecho:** QA reproducible con asserts, exit 1 al fallar, cierre del navegador, dos tamaños de ventana,
  axe, pruebas de teclado, funciones en riesgo, paleta, cambios de opacidad durante descarga y jobs simulados.
  Reportes y capturas ignorados por Git; instrucciones en `tools/e2e/README.md`.
- **Hallazgos reales:** modo «Todas» pintaba el fondo azul y un cubo opaco en 3D (mezcla del shader Niivue
  con la primera etiqueta); la tabla de 005/t0 desbordaba 6 px. Corregidos con guardas transparentes en el LUT,
  nombres alineados por etiqueta real y columnas/envoltura de tabla ajustadas.
- **Verificación parcial:** capturas de 1440×900 y 1280×800 revisadas; teclado y auditorías axe sin hallazgos
  en las pantallas comprobadas. La suite completa detectó el desborde antes del fix. **No está aprobada aún.**
- **Siguiente paso:** comprobar ambas correcciones en Chrome, obtener una pasada final de QA, revisar las
  capturas nuevas y registrar CP-027. Mantener los cambios en `feature/ux-ui`, sin merge a `main`.

### CP-027 · 2026-10-29 · F9/F10 y QA final completados
- **Hecho:** F9 y F10 terminados en `feature/ux-ui`; capas fuera del lienzo, paleta fría, cursor, atajos,
  pestañas, funciones en riesgo y tabla accesible. Corregidos los hallazgos del QA y verificados otra vez.
  El orquestador integró el trabajo de Terra/high (F9/F10), Sol/high (QA) y Astra/high (revisión independiente).
- **QA final:** `CERBERUS_UI=http://localhost:5180 npm run verify`, exit 0, **33/33 checks**, **14 auditorías
  axe con 0 violaciones automáticas**, **27 capturas**. Inicio 17:37:35 UTC, fin 17:43:15 UTC. Sin errores
  HTTP inesperados ni mutaciones reales; cuatro 404 previstos de resultados ausentes.
- **Revisión visual:** capturas a 1440×900 y 1280×800 revisadas por el agente QA y el orquestador. Confirmados
  coronal libre, fondo negro en «Todas» sin cubo azul 3D y tabla de 005/t0 legible sin desborde horizontal.
- **Checks obligatorios:** ruff y formato correctos; pyright 0 errores; pytest **425 passed, 5 deselected**;
  frontend build correcto. Se conserva el aviso conocido de bundles mayores de 500 kB.
- **Límites:** 12 auditorías axe conservan resultados incompletos; no se hizo prueba con lector de pantalla.
  Regresión visual automática inconclusa por falta de baseline. Jobs simulados, sin ANTs/MONAI ni subidas.
  Evidencia, comandos y hallazgos en `docs/QA_UX_UI.md`; runner en `tools/e2e/`.
- **Siguiente paso:** revisión del PR e integración posterior de `feature/ux-ui`. `main` no se modificó.
  El handoff identifica la rama y el estado final para retomar con Claude sin repetir la implementación.

### CP-028 · 2026-10-29 · integración de UX/UI a main · `bcef409`
- **Pedido del usuario:** realizar el merge del PR #1.
- **Hecho:** PR #1 fusionado mediante merge commit `bcef409` a las 17:49:18 UTC. `main` local actualizado
  con fast-forward; rama `feature/ux-ui` conservada. F9/F10 y el QA ya están integrados en `main`.
- **Verificación previa:** PR mergeable y limpio; sin checks de CI configurados. Ruff y formato correctos,
  pyright 0 errores, pytest **425 passed, 5 deselected** y frontend build correcto. Se comprobó que el árbol
  fusionado es idéntico al commit validado `06ba62a`; se conserva la evidencia visual de CP-027.
- **Verificación posterior:** pytest en `main`: **425 passed, 5 deselected**. Sin cambios de código después
  de la integración; este checkpoint solo actualiza documentación.
- **Checkpoint:** tablero y sección 2 de `HANDOFF.md` actualizados para retomar desde `main`. No quedan tareas
  de implementación, QA o merge pendientes de §14. Las propuestas posteriores siguen sin aprobarse.

### CP-029 · 2026-10-29 · arranque de D2 (Docker Compose)
- **Contexto:** Codex dejó un borrador de Docker (compose con redis, api, worker y frontend; Dockerfiles; grupo
  `runtime`; smoke `verify-docker.mjs`) sin build, sin pruebas y sin commit. Lo respaldó el orquestador en
  `wip/d2-docker` (`4f80a7d`).
- **Hechos:** Docker Desktop aarch64, 14 CPU, 8 GB; ANTs sin wheel ARM Linux → backend amd64 bajo Rosetta
  (verificado). `docker compose config` válido.
- **Plan:** §15 con D2a (backend), D2b (frontend) y D2c (docs). Subagentes en paralelo con propiedad de archivos
  separada; el orquestador integra y valida en Docker Desktop.
