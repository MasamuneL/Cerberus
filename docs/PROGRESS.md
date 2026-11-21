# PROGRESS — Cerberus MVP

Fuente de verdad del avance. Protocolo en [`PLAN_MVP.md` §12](PLAN_MVP.md#12-checkpoints-y-trazabilidad-entre-dispositivos).
Leyenda: ⬜ pendiente · 🟡 en curso · ✅ hecho · ⛔ bloqueado.

## Tablero

| Ticket | Estado | Rama | Commit | Fecha | Responsable / herramienta | Notas |
|---|---|---|---|---|---|---|
| HW1 · imagen CUDA + perfil GPU (§25) | ✅ | feat/HW1-cuda-gpu-profile | 9ee6bc3 | 2026-11-21 | Claude Code (orquestador Opus + hc) | PR #38; 1272 tests; cu126; validación NVIDIA pendiente; CP-074 |
| HW3 · registro ANTs fast/full (§25) | ✅ | feat/HW3-registration-mode | f1f432a | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #36; 1237 tests; fast 2.6–3.0×; CP-072 |
| REG1 · registro MNI reproducible + QC (§25) | 🟡 | feat/REG1-reproducible-registration | | | Claude Code (orquestador Opus + hc) | hallazgo de HW3; oleada 2 |
| HW4 · modo híbrido macOS (§25) | ✅ | feat/HW4-macos-hybrid | b3512c1 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #35; 1228 tests; MPS 16–34 s vs Rosetta 87–90 s; CP-071 |
| HW2 · lanzador con detección de hardware (§25) | ✅ | feat/HW2-hardware-launcher | f68173b | 2026-11-21 | Claude Code (orquestador Opus + hc) | PR #39; 1310 tests; up.ps1 sin ejecutar en Windows; CP-075 |
| UP1 · subida con find_study (§24) | ✅ | feat/UP1-upload-find-study | 8f02a18 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #34; 1224 tests; 0.64 → 0.08 ms (marginal); CP-069 |
| CFG2 · validar puertos en Vite (§24) | ✅ | feat/CFG2-vite-port-validation | bb8be2f | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #33; config sin variables idéntica; inválidos fallan al arrancar; CP-068 |
| PERF8 · reutilizar NVImage (§24) | ⛔ | — | — | 2026-11-20 | Claude Code (orquestador Opus + hc) | descartado: decodificación ≤ 8 % del toggle (gate 20 %); sin PR; CP-070 |
| ERR1 · ErrorBoundary del visor (§24) | ✅ | feat/ERR1-viewer-error-boundary | 84cc549 | 2026-11-21 | Claude Code (orquestador Opus + hc) | PR #37; e2e chunk-error 5/5 dev y preview; verify 33/33; +0.24 kB gzip; CP-073 |
| CFG1 · puertos configurables por env (§23) | ✅ | feat/CFG1-env-ports | c491be1 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #30; 1219 tests; CP-065 |
| VIZ1 · bordes suaves de máscaras (§22) | ✅ | feat/viz-smooth-masks | d1edd20 | 2026-11-20 | MasamuneL + Claude Code (revisión/merge) | PR #22; 1210 tests; e2e 33/33 + superficie + 3D; CP-063 |
| PERF1 · volumetría recortada (§21) | ✅ | feat/PERF1-volumetry-crop | 2e50217 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #26; 1191 tests; ~1.7 s → 76 ms; CP-059 |
| PERF2 · caché de volumetría (§21) | ✅ | feat/PERF2-volumetry-cache | 15e1e4d | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #28; 1195 tests; caliente < 5 ms; CP-061 |
| PERF3 · caché del predictor MONAI (§21) | ✅ | feat/PERF3-predictor-cache | 0f882b7 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #25; 1181 tests; ~0.06 s/job; CP-060 |
| PERF4 · encolar sin leer headers (§21) | ✅ | feat/PERF4-study-lookup | c9222d6 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #29; 1213 tests; 13 → 0.5 ms; CP-064 |
| PERF5 · visor diferido (§21) | ✅ | feat/PERF5-lazy-viewer | d05c119 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #27; e2e 33/33; entrada 1183→279 kB; CP-062 |
| PERF6 · caché de buffers del visor (§21) | ✅ | feat/PERF6-viewer-buffer-cache | 80dc618 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #31; e2e 33/33 + toggle 4/4; base 4 → 0 GET; CP-066 |
| PERF7 · centroide GTV (§21) | ✅ | feat/PERF7-gtv-centroid | e01ea78 | 2026-11-20 | Claude Code (orquestador Opus + hc) | PR #32; 2009 casos bit-idénticos; −19 %; CP-067 |
| FT5 · smoke y manual | ✅ | feat/FT5-smoke-manual | c891208 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #24; 1180 tests; smoke 13/13 sintético; e2e 33/33; CP-058 |
| FT4 · evaluación y exportación | ✅ | feat/FT4-evaluate-export | 1f85245 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #23; 1173 tests; métricas por paciente, baseline TC, export recargable; CP-057 |
| FT3 · transferencia y trainer | ✅ | feat/FT3-transfer-trainer | 548cd16 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #21; 1147 tests; carga estricta, head 1 logit, reanudación determinista; CP-056 |
| FT2 · preprocesamiento | ✅ | feat/FT2-preprocessing | 56f3d18 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #20; 1113 tests; remuestreo, caché verificable, preflight; CP-055 |
| FT1 · inventario y particiones | ✅ | feat/FT1-inventory-splits | 6f97eb2 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #19; 1056 tests; inventario seguro, split por paciente; CP-054 |
| FT0 · configuración y entorno de fine-tuning | ✅ | feat/FT0-training-config | 93abca3 | 2026-11-19 | Claude Code (orquestador + subagentes) | PR #18; 934 tests; CLI, esquema estricto, training-env CUDA; CP-053 |
| F12 · vista 3D y superficie GTV (§20) | ✅ | feat/viewer-3d-integration | 0e93254 | 2026-11-11 | BiomedicLJZ / Codex | PR #15 mediante #16; QA 33/33, 3D 7/7, smoke 15/15; CP-052 |
| A1c · Compose con un comando (§17) | ✅ | feat/A1c-compose-one-command | 0c03465 | 2026-11-11 | Codex | PR #14; 799 tests, smoke autenticado 15/15 y migración local; CP-051 |
| A1b · cuenta de demo automática (§17) | ✅ | feat/A1-demo-account | 47c02c2 | 2026-11-11 | Codex | PR #13; 776 tests y QA real de importación/login/preservación; CP-049 |
| B13 · Métricas y guía de segmentación | ✅ | feat/B13-segmentation-metrics | d68262a | 2026-11-10 | Codex | PR #11; integrado con A4, 766 tests y visual 33/33; CP-046 |
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
| D2a · backend en Docker (§15) | ✅ | feat/D2-docker-compose | eb081f4 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D2b · frontend en Docker (§15) | ✅ | feat/D2-docker-compose | 1331265 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D2c · docs Docker (§15) | ✅ | feat/D2-docker-compose | 5a4b229 | 2026-10-29 | Vikingo / Claude Code (orquestador) | |
| D2e-back · autoajuste + caché HTTP (§16) | ✅ | feat/D2e-autotune | e74d08a | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D2e-front · indicador de recursos + 304 (§16) | ✅ | feat/D2e-autotune | b4ef422 | 2026-10-29 | Vikingo / Claude Code (subagente) | |
| D1 · actualización documental (CP-037/038) | ✅ | main | 42d39db, f45e5e7 | 2026-11-03 | Vikingo / Codex | PR #2 y #3 integrados |
| A0 · contratos y configuración de auth (§17) | ✅ | feat/A0-auth-config | 3bd8ee4 | 2026-11-05 | Vikingo / Codex | PR #5 integrado tras QA completo; CP-041 |
| A1 · Keycloak reproducible (§17) | ✅ | feat/A1-keycloak | 5470dcf | 2026-11-05 | Vikingo / Codex | PR #6 integrado tras QA real y smoke Docker; CP-042 |
| A2 · OIDC y sesiones (§17) | ✅ | feat/A2-oidc-sessions | 7635e58 | 2026-11-06 | Vikingo / Codex | PR #8 integrado tras QA real y smoke Docker; CP-044 |
| A3 · permisos y propiedad (§17) | ✅ | feat/A3-access-control | 9674ee4 | 2026-11-06 | Vikingo / Codex | PR #9 integrado; 725 tests, visual 33/33 y Docker 15/15; CP-045 |
| A4 · UI de acceso (§17) | ✅ | feat/A4-auth-ui | d68262a | 2026-11-10 | Codex | Incorporado mediante PR #11; login real, Node 15 y UI 20; CP-046 |
| A5 · E2E y documentación de auth (§17) | ⬜ | — | — | — | — | Depende de A1–A4 y ola P del QA |
| Mantenimiento · limpieza del repositorio | 🟡 | chore/repo-cleanup | — | 2026-11-05 | Vikingo / Codex | Archivos archivados, dependencias opcionales y ramas integradas retiradas; CP-043 |

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

### CP-030 · 2026-10-29 · D2a · `eb081f4` (rama `feat/D2-docker-compose`)
- **Hecho:** backend en Docker sobre el borrador de Codex. Imagen amd64 de 1.49 GB (torch CPU ~727 MB, sin
  marimo/mayavi/pyqt), api + worker + redis *healthy*, `dcm2niix` funcional en la imagen. Fix: `USER=cerberus` y
  `HOME=/tmp` (MONAI hace `getpass.getuser()` y fallaba con UID ≠ 1000). Límites de memoria: api 2g, worker 6g.
  `storage-docker/` agregado a `.gitignore`.
- **Validación dentro de Docker (001/t0):** WT/TC/ET 53.51/31.01/20.99 cm³, **Dice TC 0.857 / WT 0.718** (igual que
  en el host); áreas: BA40 izq. arriba (3.74 cm³, 62.9 %).
- **Rendimiento con Rosetta, CPU:** segmentación 133 s con 4 hilos / 92 s con 8 (host con MPS: ~18 s); áreas 82 s
  en frío / 29 s con el registro en caché (53 s con 8 hilos). Pico del worker 4.2 GiB, sin OOM.
- **Pendiente de decidir:** `CERBERUS_CPU_THREADS` por defecto 4 (seguro) vs 8 (~35 % más rápido en 14 CPU).
- **Siguiente paso:** D2b (frontend/nginx + smoke) en curso → validación final en Docker Desktop → D2c (docs) →
  merge a main.

### CP-031 · 2026-10-29 · D2b + D2c + validación en Docker Desktop · `1331265`, `5a4b229`
- **Hecho (D2b):** imagen frontend nginx arm64 (64.7 MB), rootfs de solo lectura, usuario nginx, :8080. SPA
  fallback; proxy `/api` en streaming (timeouts de 1800 s, Range/HEAD, `client_max_body_size` = límite + 64 MB);
  assets con hash inmutables, `index.html` no-cache; cabeceras de seguridad + CSP compatible con Niivue (wasm vía
  `data:`); resolución DNS dinámica de `api`. Fixes en `verify-docker.mjs`. Compose pasa `CERBERUS_MAX_UPLOAD_MB` al
  frontend.
- **Hecho (D2c):** sección "Opción rápida: Docker Desktop" en el README (requisitos, comandos, variables,
  rendimiento medido).
- **Validación del orquestador desde cero** (`docker compose down` + `docker compose up -d --build`): el proyecto
  **cerberus** queda `running(4)` y los 4 *healthy* en 20 s (con caché); `verify-docker.mjs` 13/13 contra :8080 con
  capturas revisadas (la UI de producción se ve igual que en desarrollo); job real de áreas en 003/t0 a través de
  nginx en 89 s (79 áreas: putamen, pulvinar y caudado derechos; warning "solo T1 con contraste").
- **Pendiente de decidir:** hilos por defecto (4 vs 8). Propuesta abierta: caché HTTP de NIfTI (ETag/304 en el
  backend + `proxy_cache` en nginx), ticket D2d.

### CP-032 · 2026-10-29 · arranque de §16 (caché de volúmenes + autoajuste)
- **Decisiones del orquestador** ("como creas coherente"): Redis sigue solo como cola; la caché va en el navegador
  (ETag/304 + `no-cache`); sin `proxy_cache` en nginx. Autoajuste `auto` = min(CPUs−1, 8) leyendo cgroup, y warning
  con < 5 GB.
- **Contrato:** `SystemInfo` + `getSystem()`. Starlette 1.9 envía ETag pero no responde 304 → se implementa en el backend.
- **Siguiente paso:** D2e-back y D2e-front en paralelo → validación en Docker (incluido `--cpus 2 --memory 4g`) → CP-033.

### CP-033 · 2026-10-29 · D2e-back · `e74d08a` (rama `feat/D2e-autotune`)
- **Hecho:** `runtime.py` (CPUs por cgroup v2/v1 → afinidad → cpu_count; memoria por cgroup → meminfo → sysctl;
  dispositivo; emulación vía `VirtualApple` en cpuinfo; `resolve_threads` auto = min(CPUs−1, 8)); el worker aplica
  los hilos antes de importar torch y ANTs y publica `SystemInfo` en Redis; `GET /api/system` (con fallback si Redis
  o el worker no están); 304 condicional + `Cache-Control: no-cache` en los NIfTI; compose con `auto`. 474 tests.
- **Detección real:** host macOS = 14 CPU, 8 hilos, 36 GB, mps. Docker por defecto = 14 CPU, **8 hilos**, 6 GB,
  cpu, aviso de "emulada". `--cpus 2 --memory 4g` = **1 hilo**, 4 GB, aviso de memoria baja.
- **Hallazgo:** con `OMP_NUM_THREADS=4` fijo en el compose viejo, `nproc` daba 4 dentro del contenedor; quitarlo
  liberó los 14 CPU para la detección.
- **Verificado por el orquestador a través de nginx:** `/api/system` desde el worker y `If-None-Match` → **304, 0 B**.
- **Siguiente paso:** D2e-front (en curso) → validación → merge → CP-034.

### CP-034 · 2026-10-29 · D2e-front + merge de §16 · `b4ef422`
- **Hecho:** `SystemBadge` + `useSystemInfo` (un solo fetch, se refresca al volver a la ventana) en las pestañas
  Segmentación y Áreas: "Cálculo: CPU · 8 hilos (auto) · 6 GB · Docker" + avisos. Estimaciones: segmentación GPU
  ≈ 20 s; CPU ≈ 130 s × 4/hilos (60–400 s); áreas ~30 s–80 s × 4/hilos. Niivue carga con un `fetch` normal, así que el
  navegador puede revalidar. `verify-docker.mjs` 15/15 con chequeo del indicador y 304 vía CDP.
- **304 en el navegador:** gtv, monai_seg y brodmann vuelven 304 al regresar al estudio. `t1gd` (75 MB) vuelve 200
  en Chrome headless: probablemente supera el tamaño máximo de entrada de su caché HTTP. Con curl a través de nginx
  sí da 304. No es un fallo del servidor.
- **Validado por el orquestador:** captura del indicador revisada; stack Docker *healthy*.
- §16 mergeado a `main`.

### CP-035 · 2026-10-29 · QA y seguridad (hallazgos)
- **Pedido del usuario:** QA para buscar fallos y vulnerabilidades de datos, seguridad y código.
- **Hecho:** 4 subagentes de solo lectura (seguridad, backend, frontend, caja negra) + pip-audit / npm audit (0
  vulnerabilidades) + escaneo de secretos (ninguno). Hallazgos consolidados en **`docs/QA_2026-10-29.md`**.
- **Lo más grave:** P1 (dcm2niix copia ImageComments a `aux_file`, reproducido por el orquestador), S1 CSRF, S2 DNS
  rebinding, S3 bomba gzip NIfTI, B1/B3 errores 500 y `null` en volumetría, B4 jobs que no se cancelan.
- **QA de caja negra:** se cortó por el límite de uso; se retoma.
- **Siguiente paso:** terminar caja negra → olas de corrección P, R, F y H (sección 6 del reporte).

### CP-036 · 2026-10-29 · QA de caja negra completo
- Resultados en `docs/QA_2026-10-29.md` §5. **Nuevo y alto: Q1**, un `.nii` de 372 B tumba la API (OOM + reinicio).
  Q2: cabeceras 4D×1 acumulan memoria. Confirmados en vivo: P2, S5, B7, F8. Pasaron la validación de rutas, los ZIP
  maliciosos, los límites de tamaño y el flujo DICOM sin fugas. Limpieza de 99x verificada.
- **Siguiente paso:** ola P (P1–P3, P5, S1–S3, Q1–Q4) a la espera del visto bueno del usuario.

### CP-037 · 2026-11-03 · D1 · actualización de README y documentación
- **Pedido del usuario:** actualizar la documentación con las funciones integradas y publicarla en Git.
- **Hecho:** README con áreas de Brodmann, dominios funcionales, capas, cursor, atajos, pestañas, recursos,
  endpoints de áreas y sistema, caché 304 y variables de Docker/desarrollo. Requisitos de Node contrastados
  con el lockfile. Añadidos enlaces al handoff, QA y runners.
- **Coherencia:** `HANDOFF.md` §2 consolida el estado actual y los pendientes; los borradores históricos de
  Docker dejan de aparecer como trabajo activo. `PLAN_MVP.md` distingue el MVP original de las extensiones
  ya integradas y explica los límites del reporte de recursos y de la caché. Sin cambios de contratos ni código.
- **Privacidad y seguridad:** se retira la promesa de anonimización completa del README y se documentan
  los fallos conocidos de metadatos, temporales, CSRF, DNS rebinding y memoria. Los hallazgos del QA siguen
  pendientes; los resultados históricos de QA se conservan con sus fechas y límites.
- **Validación:** Ruff y formato correctos; pyright 0 errores; pytest **474 passed, 5 deselected**;
  frontend build correcto, con el aviso conocido de bundles mayores de 500 kB. Revisión estática contra
  rutas, modelos, componentes, runtime, Compose y lockfile; **34 enlaces locales comprobados sin errores**.
  No se repitieron tests slow ni QA visual/Docker:
  el cambio solo modifica documentación.
- **Publicación:** rama `docs/D1-refresh-documentation`; integración a `main` pendiente.
- **Siguiente paso:** revisar e integrar el cambio documental; acordar después el alcance de la ola P del QA.

### CP-038 · 2026-11-03 · D1 · aclaración de puertos Docker y desarrollo
- **Contexto:** CP-037 integrado mediante el PR #2, merge `42d39db`. El usuario pidió aclarar por qué
  la UI funciona en 8080 con Docker y no responde en 5173 sin iniciar Vite.
- **Hecho:** README con una tabla de URLs por modo: Docker/nginx en 8080 y Vite en 5173 por defecto.
  Explica que ambos sirven el mismo frontend y que Compose no inicia el servidor de desarrollo;
  la API usa 8000 en desarrollo y un puerto interno sin publicar en Docker. Añadida la referencia a
  `CERBERUS_HTTP_PORT` y contextualizado el diagrama de arquitectura como modo desarrollo.
- **Validación:** configuración contrastada con `compose.yaml`, `docker/frontend.Dockerfile` y
  `frontend/vite.config.ts`; Ruff, formato y pyright correctos; **474 tests rápidos aprobados,
  5 slow excluidos**; frontend build correcto, con el aviso conocido de bundles grandes.
  Solo documentación; no se repitieron QA visual/Docker ni tests slow.
- **Publicación:** rama `docs/D1-clarify-ports`; integración a `main` pendiente. HANDOFF §2 actualizado.
- **Siguiente paso:** revisar e integrar esta aclaración documental. Las correcciones del QA siguen pendientes.

### CP-039 · 2026-11-03 · planificación de autenticación para la demo académica
- **Pedido del usuario:** incorporar al plan el login recomendado para una demo open source con visión hospitalaria.
- **Hecho:** `PLAN_MVP.md` §17 con OIDC configurable y Keycloak incluido para autohospedaje; alcance de demo,
  arquitectura FastAPI como cliente confidencial, PKCE, sesiones opacas en Redis, expiración, CSRF y roles
  lector/analista. Se definen protección de archivos y revalidación 304, propiedad de jobs/ingestas, configuración
  prevista, endpoints futuros y criterios de aceptación. Puertos previstos: Cerberus 8080 y Keycloak 8081.
- **Planificación:** tickets **A0–A5 pendientes** en el tablero, con archivos, dependencias y pruebas.
  La aceptación final A5 depende de la ola P del QA; S1/S2 se coordinan con A3. Las olas R/F/H siguen pendientes.
  Identidad institucional, MFA obligatorio, permisos clínicos y auditoría quedan como evolución hospitalaria aparte.
- **Coherencia:** README indica que el login aún no existe; HANDOFF §2 registra la nueva fase y confirma
  la integración de CP-038 mediante el PR #3 (`f45e5e7`). Los checkpoints previos se conservan como historial.
- **Validación:** Ruff y formato correctos; pyright 0 errores; **474 tests rápidos aprobados, 5 slow excluidos**;
  frontend build correcto, con el aviso conocido de bundles grandes; **35 enlaces locales sin errores**.
  Comprobados contratos vigentes §6/§7 sin cambios, tickets A0–A5 pendientes y diff solo Markdown.
  Revisión de alcance y seguridad contra el código actual y documentación oficial enlazada en §17.
  No se ejecutó QA visual/Docker ni tests de autenticación: esta entrega solo incorpora la planificación.
- **Publicación:** rama `docs/AUTH-demo-plan`; integración a `main` pendiente. Sin código, dependencias nuevas,
  servicios de identidad instalados ni cambios en los contratos implementados.
- **Siguiente paso:** revisar e integrar el plan; cuando se solicite implementarlo, comenzar por A0 y seguir §17.5.

### CP-040 · 2026-11-05 · A0 · configuración y contratos de autenticación
- **Pedido del usuario:** continuar el plan con el inicio de sesión. CP-039 ya está integrado por el PR #4,
  merge `c2e0a4c`. Se toma únicamente A0, según el flujo de un ticket por rama.
- **Hecho:** `Settings` admite `off`/`oidc`, origen público, issuer exacto y backchannel separado, cliente,
  secreto con `SecretStr`, cookie segura y timeouts positivos/coherentes. OIDC exige credenciales; HTTP público
  y cookies inseguras quedan limitados a loopback según §17. CORS rechaza comodines en modo OIDC.
  `identity.py` define `AuthMode`, `Role` y `Principal` inmutable; `schemas.py`, TypeScript y §7 incorporan
  `AuthConfig` y `AuthSession`. README y §17 distinguen modelos disponibles de endpoints pendientes.
- **Revisión:** APIs comprobadas en Pydantic instalado. Authlib 1.9.4 declara Python ≥3.10 y BSD-3-Clause
  (fuentes primarias enlazadas en §17); compatible con Python 3.11, con conservación de avisos al incorporarla.
  No se instala ni cambia `uv.lock`; versión, seguridad y firmas se verificarán de nuevo en A2.
- **Pruebas:** **568 tests rápidos aprobados, 5 slow excluidos** (94 nuevos casos), Ruff y formato correctos,
  pyright 0 errores y frontend build correcto. Paridad Python/TypeScript comprobada generando tipos desde
  JSON Schema y compilando aserciones de igualdad contra las interfaces reales; 36 enlaces locales sin errores.
  Se conserva el aviso conocido de bundles mayores de 500 kB.
- **Revisión independiente:** encontró que la fixture de aislamiento ambiental se ejecutaba después de importar
  `main.app`. Corregido con `pytest_configure`/`pytest_unconfigure` y fixture por test. La regresión en un
  subproceso falló antes de la corrección y pasó después; verifica colección con OIDC ambiental inválido y
  restauración del entorno. Sin otros hallazgos accionables.
- **QA visual parcial:** runner vigente contra API/Vite de la rama en 5180; 10 comprobaciones completadas a
  1440×900 y 9 capturas nuevas. Se interrumpió al quedar sin avance durante axe de Segmentación, después de
  guardar su captura. Revisadas capas y segmentación, sin defectos observados; no se completó 1280×800.
  `shots/report.json` registra resultado parcial 10/13, errores de navegador cerrado tras SIGINT y exit 130;
  no es una aprobación global. Las capturas restantes de ejecuciones anteriores conservan su fecha histórica.
- **Límites:** sin rutas de login, Keycloak, sesiones, permisos ni UI; configurar `oidc` todavía no protege
  recursos en esta versión. QA de seguridad y A1–A5 siguen pendientes. No se ejecutaron tests slow ni E2E de auth.
- **Publicación:** implementación `ff989ea` en `feat/A0-auth-config`, subida y disponible en el
  [PR #5](https://github.com/MasamuneL/Cerberus/pull/5), pendiente de revisión/integración a `main`.
  El tablero conserva A0 🟡 hasta el merge. Siguiente paso: integrar A0 y entonces tomar A1.

### CP-041 · 2026-11-05 · A0 integrado tras QA completo
- **Autorización:** continuar los tickets posibles, hacer commits/push frecuentes y ejecutar QA antes del merge.
- **QA previo al merge:** runner vigente sin cambios, 13:43:05–13:48:52 UTC, exit 0; **33/33 checks**, 14
  auditorías axe sin violaciones automáticas y 27 capturas. Revisadas capas 1440×900 y tabla 005/t0 a 1280×800.
  El bloqueo de CP-040 no se reprodujo; no se omitieron comprobaciones ni se modificó el runner.
- **Checks:** Ruff/formato/pyright correctos, **568 tests rápidos aprobados, 5 slow excluidos**, build correcto.
  Árbol del merge idéntico al commit validado `36812e4`; cambios posteriores solo documentales.
- **Integración:** PR #5 fusionado mediante merge `3bd8ee4`. A0 ✅; login, permisos y UI todavía pendientes.
- **Siguiente paso:** A1 en rama aislada, conservando los cambios de limpieza ajenos en el checkout principal.

### CP-042 · 2026-11-05 · A1 · proveedor reproducible integrado
- **Hecho:** overlay `compose.auth.yaml` con Keycloak 26.8.1 y PostgreSQL 18 por digest, red privada para la base,
  seis servicios sanos y puertos de host solo loopback (8080 app, 8081 proveedor). `realm.json` sin usuarios,
  cliente confidencial con callback exacto y PKCE S256; mapper de roles limitado a `cerberus-web`.
  Bootstrap genera `.env.auth` 0600 sin mostrar secretos ni sobrescribir archivos existentes. README y §17 actualizados.
- **Desviación necesaria:** Debian HTTP devolvía 403 en el build limpio; Dockerfile cambia repositorios a HTTPS
  manteniendo firmas. Reconstrucción completa y arranque real correctos.
- **Checks:** Ruff/formato/pyright correctos, **575 tests rápidos aprobados, 5 slow excluidos**, build correcto.
  Siete tests nuevos cubren bootstrap, permisos, entorno, valores inválidos y preservación del archivo existente.
- **QA del proveedor:** metadata y JWKS desde API con issuer público y transporte interno; callback exacto,
  redirect ajeno rechazado, registro público desactivado. Cuentas temporales reader/analyst: Authorization Code
  con PKCE en Chrome y claim real correcto. Tras reiniciar PostgreSQL/Keycloak, mismas cuentas, roles y contraseñas
  siguen funcionando; cuentas de QA eliminadas. Captura en español revisada.
- **QA Docker previo al merge:** 2026-11-05 14:01:13–14:04:13 UTC, exit 0, **15/15 checks**, 11 capturas y ningún
  pendiente. Revisadas capturas de recursos 1440×900 y volumetría 1280×800. Revisión independiente sin hallazgos.
- **Integración:** PR #6, merge `5470dcf`; árbol igual al commit validado `111811d`. Checkpoint documental posterior.
- **Límites y siguiente paso:** A2 (OIDC y sesiones), luego A3 (protección) y A4 (UI). A1 todavía no protege
  los recursos de Cerberus; A5 y ola P pendientes. Trabajo aislado en `/private/tmp/cerberus-auth-A1`; secretos
  locales en `.env.auth`, ignorados por Git. Se conservan cambios ajenos de limpieza en el checkout principal.

### CP-043 · 2026-11-05 · limpieza reversible del repositorio
- **Pedido del usuario:** retirar archivos de menor utilidad, mover el notebook a otra carpeta de BigData,
  poner en cuarentena lo dudoso, eliminar ramas obsoletas y actualizar Graphify tras cada bloque importante.
- **Archivo:** `cerberus_eda.py` y `cerberus_mayavi.py` conservados byte por byte fuera del repo, con SHA-256;
  enlaces a `Data/` y `models/` mantienen sus rutas. El `main.py` de ejemplo y las cachés raíz se conservan
  en cuarentena. No se retiran datos, modelos, resultados, configuraciones del IDE ni evidencias de QA.
  [`ARCHIVO.md`](ARCHIVO.md) documenta ubicación, integridad, recuperación desde Git y ejecución.
- **Dependencias:** diez requisitos específicos del notebook pasan a un grupo opcional; `runtime` y todas
  las versiones del lockfile se conservan. Sincronización normal retira 41 paquetes exclusivos del entorno
  anterior; `.venv` baja aproximadamente de 2.1 GB a 1.1 GB. `marimo check` del original archivado correcto.
- **Ramas:** 30 locales y 29 remotas integradas eliminadas inicialmente, con bundle completo verificado,
  inventario de SHA y borrado remoto atómico condicionado al SHA. A0/A1 se integraron durante esta sesión;
  tras un respaldo adicional se retiraron sus ramas, sin worktrees activos: total **32 locales y 31 remotas**.
  Se conservan `main`, la limpieza, A2 activo y los dos borradores `wip` con commits no integrados.
- **Concurrencia:** limpieza actualizada sobre `ec34d25` (A1 integrado), conservando las entregas de la otra
  sesión. Sin cambios en código de backend/frontend, Compose ni contratos de disco/API.
- **Graphify:** CLI 0.9.102 temporal, extracción AST local sin LLM; configuración en `.graphifyignore`.
  Regenerado tras archivar, limpiar ramas e incorporar A1; `graph.json`, `graph.html` y `GRAPH_REPORT.md`
  locales, ignorados por Git. Después el usuario autorizó instalarlo: disponible de forma persistente
  en `~/.local/bin/graphify`, con entorno aislado de uv; sin dependencias nuevas en Cerberus.
  Los documentos no se indexan en este modo.
- **Checks:** Ruff y formato correctos, pyright sin errores, **575 tests rápidos aprobados, 5 slow excluidos**;
  build correcto con el aviso conocido de bundles grandes. Versiones del lockfile, grupo `runtime`, hashes
  de originales, enlaces de datos y 50 enlaces Markdown locales comprobados. Tests slow no ejecutados.
- **QA visual:** primer intento 13/17 checks, exit 1, por detenerse Vite compartido durante la ejecución;
  conexión rechazada al seleccionar 005/t0 y abrir el segundo tamaño. Repetición completa con API/Vite propios
  en 5182, 14:09:00–14:14:44 UTC: **33/33 checks**, 14 auditorías axe sin violaciones automáticas,
  27 capturas y exit 0. Revisadas capas y segmentación a 1440×900 y tabla 005/t0 a 1280×800,
  sin regresiones observadas. Sin modificar el runner ni ejecutar modelos o subidas reales.
- **Publicación:** rama `chore/repo-cleanup`, pendiente de revisión/integración. Siguiente paso: revisar
  e integrar el PR de mantenimiento; el desarrollo de A2 sigue en su worktree independiente.


### B13 · Métricas de concordancia y guía (2026-11-10, pendiente de merge)

- Rama `feat/B13-segmentation-metrics`, basada en `chore/repo-cleanup`.
- Backend: Dice/F1, recall, precisión, HD95 simétrico y error de volumen firmado para TC/WT frente a GTV;
  casos vacíos explícitos, JSON antiguos compatibles. Contrato ampliado en §7/§18 del plan.
- UI: apartado de métricas y guía desplegable; distingue concordancia por estudio de validación del
  modelo y certeza clínica. Resultados anteriores solicitan volver a segmentar.
- Validación: 582 tests rápidos aprobados, 5 slow excluidos; Ruff, formato, pyright y build correctos.
  QA visual: 33/33 checks, 14 auditorías axe sin violaciones automáticas, 27 capturas; revisadas
  capturas de Segmentación a 1440×900 y 1280×800. El primer intento de Chrome falló por sandbox;
  la ejecución autorizada fuera del sandbox completó correctamente. Sin inferencia ni subidas reales.
- Pendiente: revisar/integrar PR y registrar checkpoint posterior al merge. No se modifica autenticación.

### CP-044 · 2026-11-06 · A2 · OIDC y sesiones integrados
- **Hecho:** rutas config/login/callback/me/logout; cliente Authlib 1.9.4 + HTTPX2 2.15.1, firma RS256 mediante
  joserfc 1.8.0 y validación OIDC. Transacciones de 300 s ligadas al navegador y de un uso; sesiones Redis con
  cookie opaca HttpOnly/Lax, renovación, expiración por inactividad y absoluta, logout con CSRF/Origin.
  Estado de sesión público limitado a roles, vencimiento y CSRF. Modo off conserva 404 salvo config.
- **Seguridad y revisión:** regresiones RED→GREEN de `azp` falso/vacío y claim de roles omitido por Keycloak
  (403 sin rol); query del callback fuera de logs de Uvicorn incluso si fallan dependencias. Reproducida fuga
  de nginx con API caída, con y sin barra final; corregida y comprobada con marcadores sintéticos. Revisión
  independiente sin otros hallazgos verificables. APIs comprobadas en los paquetes instalados; sin criptografía propia.
- **Checks:** Ruff/formato/pyright correctos, **649 tests rápidos aprobados, 5 slow excluidos**; build correcto
  con aviso conocido de bundles grandes y 37 enlaces locales sin errores. Fakeredis/Lua solo en dev, sin red en tests.
- **QA real previo al merge:** Chrome, Keycloak y Redis: lector/analista, cuenta sin rol, renovación, CSRF/Origin,
  logout e identificador viejo; state incorrecto/otro navegador/replay. Proveedor caído conserva sesión válida y
  nuevos logins dan 503; Redis caído da 503. Caducidad real con 2 s idle/5 s absolutos, luego valores por defecto
  restaurados y cuentas temporales eliminadas. Respuestas y cookies sin tokens del proveedor.
- **Smoke Docker previo al merge:** 2026-11-06 21:30:11–21:32:50 UTC, exit 0, **15/15 checks**, 11 capturas,
  ningún pendiente. Revisadas recursos 1440×900 y volumetría 1280×800; sin regresiones observadas.
- **Integración:** PR #8, merge `7635e58`; árbol idéntico al commit validado `cbb8d3e`. CP-043 está reservado
  por la limpieza en PR #7, aún pendiente; este checkpoint no modifica ni integra ese trabajo.
- **Siguiente paso:** A3 para imponer permisos/propiedad/CSRF/Host en recursos, después A4 UI. A2 todavía no
  protege catálogo, archivos, jobs ni subidas; A5 requiere ola P. Worktree `/private/tmp/cerberus-auth-A1` conservado.


### CP-045 · 2026-11-06 · A3 · Permisos y propiedad integrados
- **Hecho:** middleware antes del body/I/O para sesión, lector/analista y propiedad Redis por (`issuer`, `sub`).
  Registra propietarios antes de encolar, limpia errores/confirmación/descarte y alinea TTL con resultados arq.
  Recursos ajenos o sin metadata devuelven 404. Catálogo final compartido; JSON `no-store`, NIfTI `private, no-cache`
  y permisos antes de GET/HEAD/304. Swagger/ReDoc/OpenAPI deshabilitados en OIDC.
- **S1/S2:** CSRF y Origin en OIDC; `X-Cerberus: 1` y Origin autorizado cuando venga en modo local. Host validado
  por API/nginx. CLI web añade cabecera local automáticamente. La privacidad y las reglas DICOM previas se conservan.
- **Revisión:** cerrados bypass por `root_path` y propietarios permanentes por fallos tempranos de arq.
  `OwnedWorker.finish_failed_job` cubre expiración, deserialización, función ausente, retries y abort. Nuevo comando
  `uv run python -m cerberus_api.worker`; healthcheck oficial `arq --check` conservado. Regresiones con arq real
  sobre fakeredis; revisión independiente sin hallazgos pendientes.
- **Checks:** Ruff/formato/pyright y build correctos; **725 tests rápidos aprobados, 5 slow excluidos**. Comprobados
  39 enlaces locales. Aviso conocido de bundles grandes, sin fallo de build.
- **QA real:** Keycloak/Redis, lector y dos analistas, mutaciones/CSRF, acceso cruzado, ingesta sintética fallida,
  TTL de job, propiedad tras nuevo login, descarte y GET/HEAD condicional después de logout (401). Repetida regresión
  A2 completa con nuevo launcher: state/replay, proveedor/Redis caídos e idle/absoluta bajo actividad. Cuentas temporales
  eliminadas y timeouts restaurados. Worker Docker también verificado con función ausente/retries agotados.
- **QA visual:** Vite, 22:01:16–22:07:03 UTC: **33/33 checks**, 14 auditorías axe sin violaciones automáticas,
  27 capturas y exit 0. Smoke Docker, 22:08:20–22:11:07 UTC: **15/15**, 11 capturas, sin pendientes. Revisadas
  ambas resoluciones. El wrapper falló al restaurar por cwd; corregido y restaurado manualmente: modo OIDC y
  catálogo anónimo 401 verificados. El runner aprobó todas sus comprobaciones.
- **Integración:** PR #9, merge `9674ee4`; árbol idéntico al commit validado `e3345c2`. CP-043/PR #7 siguen en
  la rama de limpieza ajena. Worktree `/private/tmp/cerberus-auth-A1` y `.env.auth` local ignorado se conservan.
- **Siguiente paso:** A4 (UI de acceso), luego dependencias de ola P y A5. La interfaz aún no refleja roles ni incluye
  login/logout: el acceso se inicia manualmente en `/api/auth/login`. S1/S2 cerrados; resto de ola P pendiente.


### Validación previa a integración A4/B13 · 2026-11-10

El usuario autoriza merge a main y documentar `demo` / `demo`. Se integra A4 (`52ebb0b`) en la
rama de B13, conservando limpieza CP-043, nota para Astra y dependencias de autenticación.
Lockfile resuelto sin cambiar versiones respecto a A4. README refleja A0–A4 y las credenciales
verificadas de la instancia local; el bootstrap no crea la cuenta automáticamente.

Checks: **766 tests rápidos aprobados, 5 slow excluidos**; Ruff, formato, pyright y build correctos.
Node: 5 pruebas de medios y 10 de sesión; UI controlada: 12 escenarios generales y 8 de sesión.
QA real Docker con `demo`: login, API autenticada con métricas, logout con 401 y contraseña exigida
al volver, tanto con «Recordarme» como sin él. Cookie de recuerdo solo con la opción activada.
QA visual final: **33/33 checks**, 14 auditorías axe sin violaciones automáticas y 27 capturas;
revisadas Segmentación a 1440×900 y 1280×800. Primer intento interrumpido tras detectar una carrera
en la aserción de capas; el runner ahora espera la presencia/ausencia solicitada del volumen antes
de comprobarla. La repetición completa pasó. No se ejecutan modelos ni subidas en la suite visual.


### CP-046 · 2026-11-10 · A4, B13 y documentación integrados en main

- **Integración autorizada:** PR #11, merge `d68262a`; incorpora la limpieza CP-043 y el head A4
  `52ebb0b`, además de métricas B13 y nota de fine-tuning para planificar posteriormente con Astra.
- **Acceso demo:** README documenta usuario `demo` y contraseña `demo`; login/logout verificados
  contra Docker. Se aclara que el bootstrap no crea esa cuenta automáticamente.
- **Validación:** árbol de código idéntico al head verificado `b8c4cfb`; 766 tests rápidos aprobados,
  5 slow excluidos, Ruff/formato/pyright y build correctos. Node 15/15 y UI de autenticación 20/20.
  QA visual final 33/33, 14 auditorías axe sin violaciones automáticas y 27 capturas revisadas en
  Segmentación a 1440×900 y 1280×800. QA real de contraseña/Recordarme y API con métricas aprobado.
- **Reproducibilidad:** main conserva pantalla de login y prompt=login junto con métricas; ya no
  requiere ensamblar fuentes de snapshots. Docker local sigue ejecutando la combinación A4+B13
  validada previamente; no se reinició durante este merge para evitar interrumpir trabajos.
- **Estado posterior:** A4 y B13 completados; A5 y ola P pendientes. Fine-tuning solo documentado,
  sin entrenamiento iniciado. Checkout principal actualizado a main y checkpoint subido.


### CP-047 · 2026-11-10 · Documentación del mapeo de Brodmann

- Solicitud del usuario: incorporar al README herramientas, adaptación del atlas y fórmulas del reporte.
- Se documentan ANTs SyN, Nilearn, NiBabel, NumPy/SciPy y Niivue; selección T1, máscara cerebral,
  exclusión GTV+5 mm del costo, transformación inversa y solapamientos/distancias por área.
- Hallazgo pendiente explícito: atlas en Talairach y registro a MNI152 sin conversión explícita;
  la suposición del plan sobre el espacio del atlas necesita corregirse o verificarse.
- Validación documental: `git diff --check` correcto y enlaces locales del README resueltos.
  Sin cambios de código ni nuevas ejecuciones de tests, modelos o QA visual.

### En revisión · 2026-11-11 · D2b: arranque Docker en Windows

- Rama `feat/D2b-windows-entrypoint`: CRLF en el heredoc produce un shebang `/bin/sh\r`
  y reproduce exactamente el error de arranque reportado. Normalización durante build y LF
  en `.gitattributes`; README documenta reconstrucción y diagnóstico de sesión.
- Reproducción antes del cambio: LF arranca, CRLF termina con código 255. Tras corregir,
  ambos arrancan, `nginx -t` pasa con raíz de solo lectura y se rechazan límites inválidos.
  Build completo con Dockerfile CRLF correcto; healthz y proxy de auth responden desde imagen nueva.
- 766 tests rápidos aprobados, 5 slow excluidos; Ruff, formato, pyright y build frontend correctos.
  12 escenarios de auth UI y 8 de continuidad/sesión aprobados con HTTP controlado; login revisado
  visualmente. No se ejecutó la suite visual Vite ni autenticación con proveedor real.
- Pendiente: integrar PR y registrar checkpoint. La segunda captura necesita logs del equipo afectado.

- **QA ampliado antes del merge:** visual Vite 33/33 (14:21:03–14:26:29 UTC), 14 auditorías axe
  sin violaciones automáticas y 27 capturas; smoke Docker final 15/15 sin pendientes
  (14:32:22–14:34:57 UTC), 11 capturas; revisadas ambas resoluciones. Auth UI 12/12 y
  continuidad/sesión 8/8, Node 15/15 y login/logout real con Keycloak aprobados.
  La imagen construida con Dockerfile CRLF sirve catálogo autenticado; tras logout,
  `/api/auth/me` y catálogo devuelven 401. No se ejecutan inferencias ni subidas reales.
- El primer smoke quedó 14/15: cancelaciones al actualizar capas se contaban como fallos de red.
  Diagnóstico ubicó los tres abortos en la carga inicial; se interrumpió la pasada diagnóstica
  después de localizarlos. El runner ahora registra cancelaciones NIfTI y exige un reemplazo
  posterior completo; cinco casos positivos/negativos confirman que errores HTTP, descargas
  antiguas, otros archivos y falta de reemplazo siguen bloqueando. Repetición completa correcta.

### CP-048 · 2026-11-11 · D2b: Docker compatible con CRLF de Windows

- **Integración autorizada tras QA:** [PR #12](https://github.com/MasamuneL/Cerberus/pull/12),
  merge `7644d87`; árbol idéntico al head validado `027c6c6`.
- `docker/frontend.Dockerfile` normaliza el script de entrada; `.gitattributes` conserva LF
  en Dockerfiles. README documenta reconstrucción y diagnóstico de sesión. Build completo LF/CRLF,
  arranque sin privilegios con raíz de solo lectura, `nginx -t` y checkout con autocrlf correctos.
- **QA:** Ruff/formato/pyright, 766 tests rápidos (5 slow excluidos), build frontend y 15 pruebas
  Node correctos. Visual Vite 33/33, 14 auditorías axe sin violaciones automáticas y 27 capturas;
  smoke Docker 15/15 sin pendientes y 11 capturas. Revisadas ambas resoluciones. Auth UI 12/12 y
  continuidad/sesión 8/8; Keycloak real: login, `prompt=login`, catálogo autenticado en imagen CRLF
  y logout que devuelve sesión/catálogo a 401.
- El smoke detectó cancelaciones previstas al llegar reportes de capas. Se corrigió el runner
  para exigir un reemplazo posterior completo por volumen, con cinco casos positivos/negativos.
  Se conserva la evidencia del fallo inicial y la interrupción diagnóstica en la entrada anterior;
  la aprobación final corresponde a una ejecución completa posterior, sin relajar errores HTTP.
- No se ejecutaron modelos, subidas reales ni Windows nativo: se reprodujo CRLF y autocrlf
  desde macOS/Docker. La demo existente conserva sus contenedores; solo se usaron servicios QA aislados.
- **Siguiente paso:** actualizar el repositorio y reconstruir el frontend del profesor en Windows.
  La segunda captura requiere logs si persiste «Servicio no disponible». A5 y ola P siguen pendientes.

### En revisión · 2026-11-11 · A1b: cuenta de demo automática

- Solicitud del usuario: evitar crear y configurar manualmente la cuenta del profesor.
  Rama `feat/A1-demo-account`: seed con `demo` / `demo` y rol `analyst` de `cerberus-web`;
  perfil ficticio con nombre, apellido y correo `.invalid`, sin acciones iniciales obligatorias.
- `sync_realm.py` importa ese usuario con `ifResourceExists=SKIP`. En un realm existente,
  crea la cuenta si falta, conservando contraseña, roles, acciones requeridas y estado si existe.
  README y PLAN_MVP §17 reflejan la excepción de credenciales públicas para la demo de loopback.
- Validación: 776 tests rápidos aprobados, 5 slow excluidos; Ruff y formato de backend/scripts auth,
  pyright y build frontend correctos. Pruebas sin red: seed, importación/skip, errores HTTP,
  respuesta inválida y ausencia de credenciales en errores.
- Keycloak 26.8.1 aislado: importación inicial desde cero, login real Authorization Code+PKCE,
  claim `analyst`, creación en realm sin demo y sincronización repetible. Preservación comprobada
  tras cambiar contraseña, pasar a rol `reader`, exigir cambio de contraseña y deshabilitar la cuenta.
  La primera pasada real pidió completar perfil; se añadieron datos ficticios y se repitió con éxito.
  Captura en español revisada; sin cambios a cuentas ni servicios de demo existentes.
- Pendiente integrar PR y registrar checkpoint. No se repitieron las suites completas del visor
  ni smoke de nginx; no se ejecutaron inferencias o subidas. El 502 del profesor necesita sus logs.

### CP-049 · 2026-11-11 · A1b: cuenta de demo automática integrada

- **Integración:** [PR #13](https://github.com/MasamuneL/Cerberus/pull/13), merge `47c02c2`;
  árbol idéntico al head validado `20d69be`.
- Las instalaciones nuevas incluyen la cuenta pública local `demo` / `demo`, perfil ficticio
  completo y rol `analyst`. En instalaciones anteriores, el comando documentado de sincronización
  la crea solo si falta mediante SKIP, sin modificar cuentas existentes ni conceder administración.
- **Checks:** 776 tests rápidos aprobados, 5 slow excluidos; Ruff/formato de backend/scripts auth,
  pyright (incluido `sync_realm.py` por separado) y build frontend correctos.
- **QA real:** Keycloak 26.8.1 aislado; importación desde cero, login Authorization Code+PKCE
  sin formularios extra y claim `analyst`, alta en realm existente y repetición sin cambios.
  Preservados contraseña cambiada, rol `reader`, acciones requeridas y cuenta deshabilitada.
  Captura del formulario en español revisada. No se repitieron visor completo ni smoke nginx;
  no se ejecutaron modelos o subidas ni se modificaron cuentas de la demo existente.
- **Siguiente paso:** actualizar el checkout del profesor y ejecutar la sincronización con Keycloak
  listo si ya tenía un realm. El HTTP 502 requiere sus logs; crear una cuenta no corrige conectividad.

### CP-050 · 2026-11-11 · Docker local actualizado desde main

- **Operación solicitada:** reconstruidas imágenes de API/worker y frontend desde `42d4358` de main,
  recreados esos tres servicios y Keycloak con los archivos actuales. Imágenes activas:
  backend `52559c4cb966`, frontend `ef249ef7c571`. Los 28 archivos del backend coinciden con main;
  el historial de la imagen frontend incluye normalización CRLF y el seed activo incluye `demo`.
- La configuración anterior referenciaba `/private/tmp/cerberus-auth-A1`, ya desaparecida.
  Se recuperaron los mismos secretos del entorno de los contenedores, sin imprimirlos, y se guardaron
  en `.env.auth` de la raíz con permisos 0600 e ignorado por Git. Compose ahora opera desde el checkout
  principal con ambos archivos y `--env-file .env.auth`.
- **Preservación:** entorno efectivo conservado para seis servicios; mismos volúmenes de PostgreSQL/Redis
  y montajes Data/storage/models. Verificados cuenta, roles y credenciales existentes antes/después de
  sincronizar; `sync_realm.py` informa «sin cambios». Los 46 archivos de resultados conservan tamaños,
  mtimes y hashes JSON después del QA. No había jobs en progreso ni en cola al reiniciar el worker.
- **Verificación:** seis servicios healthy, salud 200 y auth/config OIDC. Navegador real final
  15:07:10–15:07:44 UTC: `demo` / `demo`, rol analyst, Niivue con 001/t0 y volumetría GTV 33.14 cm³;
  logout vuelve a 401 en sesión, catálogo y NIfTI. Tres capturas, incluidas 1440×900 y 1280×800,
  revisadas en `tools/e2e/shots/local-main-update/`.
- Solo cambian documentos de estado; no se repitieron suites completas, modelos ni subidas.
  **Siguiente paso:** recoger logs del profesor para su HTTP 502, independiente de esta actualización local.

### En revisión · 2026-11-11 · A1c: Compose autenticado con un comando

- Pedido del usuario: eliminar bootstrap, overlay y configuración manual para iniciar la demo.
  `compose.yaml` incluye identidad e inicializadores; `compose.auth.yaml` mantiene compatibilidad.
  Secretos aleatorios persistentes en tres volúmenes separados; migración desde `.env.auth`, claves
  no reemplazables y bloqueo de una base anterior sin claves recuperables. Directorios nuevos vacíos
  de storage/models reciben el UID/GID del contenedor, sin cambiar datos o propietarios existentes.
- `setup-identity` conserva usuarios con SKIP y gestiona exclusivamente origen/callback de cerberus-web,
  manteniendo secreto y PKCE. El puerto público deriva ambas URLs; origen explícito validado antes de
  enviar credenciales, incluyendo rechazo de comodines. API espera a ese setup y lee solo su secreto.
- Checks: Ruff/formato backend y scripts auth, pyright, 799 tests rápidos (5 slow excluidos) y build
  frontend correctos. Compose se valida sin red y sin archivos de secretos, con puertos 8080/8082 y
  ambos formatos de comando. Smoke autenticado con sesión real: 15/15, sin pendientes,
  16:08:51–16:09:38 UTC; 11 capturas, ambas resoluciones revisadas. Soporte opcional de storageState
  para el runner; no se desactiva autenticación.
- QA real aislado: instalación sin `.env.auth` ni volúmenes, cuenta demo operativa; reinicio completo y
  cambio de puerto conservaron claves, contraseña cambiada, rol reader, estado deshabilitado y acciones
  requeridas. Callback actualizado automáticamente; login posterior con la contraseña conservada correcto.
- Docker local migrado mediante el comando único: claves originales adoptadas, cuentas/credenciales
  y 46 archivos de resultados intactos; seis servicios healthy y dos inicializadores con salida 0.
  QA local 16:14:40–16:15:14 UTC: demo/demo, analyst, visor 001/t0, GTV 33.14 cm³ y logout con 401.
- No se ejecutaron inferencias, subidas ni suite Vite completa. A5/ola P siguen pendientes.
  Plan breve: `docs/superpowers/plans/2026-11-11-compose-one-command.md`.

### CP-051 · 2026-11-11 · A1c: arranque autenticado con un comando

- **Integración:** [PR #14](https://github.com/MasamuneL/Cerberus/pull/14), merge `0c03465`;
  árbol idéntico al head validado `89d21a6`. Docker local ya ejecuta esa implementación.
- `docker compose up -d --build` prepara secretos persistentes, PostgreSQL/Keycloak y cuenta demo,
  sin Python en el host ni pasos manuales. Seis servicios healthy y dos inicializadores con salida 0.
  El overlay anterior conserva compatibilidad; el desarrollo nativo mantiene su configuración.
- `CERBERUS_HTTP_PORT=8082` configura origen/callback automáticamente. Se validaron instalación
  desde cero, reinicio, cambio de puerto y preservación de claves, contraseña, roles y estado.
  El conflicto del profesor quedó localizado en `openshell-gatew`, que atiende 127.0.0.1:8080.
- **Checks:** 799 tests rápidos, 5 slow excluidos, Ruff/formato/pyright y build correctos.
  Smoke autenticado con sesión real: 15/15, sin pendientes; 11 capturas y ambas resoluciones revisadas.
  Migración local: mismas tres claves, cuentas/credenciales y 46 resultados intactos; login demo/demo,
  analyst, visor 001/t0, GTV 33.14 cm³ y logout que vuelve a 401 en sesión/catálogo/NIfTI.
- Los archivos de sesión temporal y el proyecto QA aislado se eliminaron al terminar. Se conservaron
  todos los volúmenes locales de la aplicación. No se ejecutaron modelos, subidas ni suite Vite completa.
  A5 y ola P siguen pendientes. **Siguiente paso:** actualizar el clon del profesor y arrancar en 8082.


### En revisión · 2026-11-11 · F12: superficie GTV y vista 3D del PR #15

- [PR #16](https://github.com/MasamuneL/Cerberus/pull/16) conserva los commits del
  [PR #15 de BiomedicLJZ](https://github.com/MasamuneL/Cerberus/pull/15) (`bbb72ed`).
  Superficie GTV, máscara cerebral, iluminación/bordes/silueta, corte, cámara y orientación.
- Correcciones: extracción nativa y componentes pequeños sin suavizado; grid de máscara validado
  (dimensiones y affine), aviso de incompatibilidad, liberación de buffers y restauración de ajustes
  al volver a 2D. Setters omitidos si 2D ya está restablecido. Pruebas de auth adaptadas a imports mixtos.
- Ruff/formato/Pyright, **799 tests rápidos**, 5 slow excluidos y build correctos. Geometría y grid,
  12 escenarios de visor/cancelación y 10 pruebas de sesión correctos. Revisión independiente cerrada.
- QA general final 22:04:32–22:10:38 UTC: **33/33**, 14 auditorías axe sin violaciones automáticas,
  27 capturas. 3D 22:10:38–22:15:51 UTC: **7/7**, axe del panel en ambos tamaños y seis capturas.
  Auth UI: **20/20**. Smoke del build compilado: **15/15**, sin pendientes; capturas revisadas.
- Las pasadas interrumpidas y la de 31/33 por fuentes HTTP 403 no son aprobaciones. El 403 provenía
  del enlace de dependencias fuera del allowlist de Vite; corregido con dependencias locales y
  repetición completa. No se cambió el runner para ignorar errores ni se omitieron comprobaciones.
- Smoke sobre Vite preview/API local; no reconstruye Docker. Auth UI con HTTP controlado; no repite
  Keycloak real. Sin modelos, registros ni subidas. Contratos §6/§7 intactos; A5/ola P pendientes.


### CP-052 · 2026-11-11 · F12: vista 3D y superficie GTV integradas

- **Integración:** [PR #15](https://github.com/MasamuneL/Cerberus/pull/15) incorporado mediante
  [PR #16](https://github.com/MasamuneL/Cerberus/pull/16), merge `0e93254`. Ambos figuran merged;
  commits del profesor conservados y árbol idéntico al head validado `1915451`.
- Superficie GTV nativa, máscara cerebral compatible, controles de render, corte, cámara y cubo
  de orientación. Focos mínimos conservados, liberación de mallas y restauración 2D verificadas.
- **Checks:** 799 tests rápidos (5 slow excluidos), Ruff/formato/Pyright, build, regresiones de geometría
  y grid, 12 escenarios de visor/cancelación y 10 pruebas de sesión correctos. Revisión independiente cerrada.
- **QA final:** general 33/33 (22:04:32–22:10:38 UTC), 14 auditorías axe sin violaciones automáticas,
  27 capturas; 3D 7/7 (22:10:38–22:15:51 UTC), axe del panel y seis capturas; auth UI 20/20;
  smoke 15/15 (22:16:08–22:18:42 UTC), sin pendientes y 11 capturas. Ambas resoluciones revisadas.
- La aprobación corresponde a esas pasadas finales; interrupciones y fuentes HTTP 403 del entorno
  previo quedan documentadas arriba. Smoke con Vite preview/API local, sin reconstrucción Docker;
  auth UI con HTTP controlado, sin nueva prueba de Keycloak real. Sin inferencias ni subidas.
- README, plan §20, runners y handoff actualizados. Contratos §6/§7 intactos. D3 sigue separado;
  A5 y las correcciones de la ola P siguen pendientes.

### CP-053 · 2026-11-19 · FT0: configuración, CLI y entorno CUDA del pipeline de fine-tuning

- **Integración:** [PR #18](https://github.com/MasamuneL/Cerberus/pull/18), merge `93abca3`. Incluye
  `docs/PLAN_PIPELINE_FINETUNING.md` (plan FT0–FT5).
- Paquete `backend/cerberus_training/` (Hatch): esquema JSON estricto (`strict`, `extra="forbid"`,
  `schema_version` 1), ejemplo `configs/training/gtv_binary.json`, CLI con los subcomandos del plan;
  los pendientes salen con código 3. Extras: `validate` y `device` (capability y arquitecturas CUDA).
- Entorno CUDA aparte en `training-env/` (torch 2.14.1+cu126, lock propio); `uv.lock` raíz y ruedas
  CPU de la app intactos. No probado en GPU real; cu126 puede no cubrir `sm_120` (documentado).
- **Checks:** Ruff/formato/Pyright y 934 tests rápidos (5 slow excluidos). Revisión independiente aplicada.
  Frontend sin cambios. Sin datos reales, entrenamiento ni evaluación. Contratos §6/§7 intactos.
- Siguiente: FT1 (inventario y particiones) en `feat/FT1-inventory-splits`.

### CP-054 · 2026-11-19 · FT1: inventario de CFB-GBM y particiones por paciente

- **Integración:** [PR #19](https://github.com/MasamuneL/Cerberus/pull/19), merge `6f97eb2`.
- `inventory`: `data_root` de solo lectura, ids validados con `sequences` antes de construir rutas,
  traversal/symlinks externos rechazados, cabecera cruda para spacing y coherencia con el affine,
  perfil estricto (T2* nunca sustituye T2), GTV ausente excluye y GTV vacía se marca para revisión.
  Carpetas rechazadas sin nombre en bruto (`name_sha8`). `read_inventory` revalida el manifest.
- `split`: 70/15/15, seed 42, `largest_remainder_v1`, duplicados unidos (union-find), `splits.json`
  inmutable con hash y publicación exclusiva; avisos si las cuotas se desvían.
- **Checks:** Ruff/formato/Pyright y 1056 tests rápidos (5 slow excluidos). Revisión independiente
  aplicada (13 puntos). Sin datos reales ni entrenamiento.
- **Riesgo:** en `Data/` local solo 1 de 8 estudios cumple el perfil estricto (falta `t2tse`). La
  convención TCIA real no está verificada; solo `cerberus_v1` (como `Data/001`).
- Siguiente: FT2 (preprocesamiento).

### CP-055 · 2026-11-19 · FT2: preprocesamiento, caché verificable y preflight

- **Integración:** [PR #20](https://github.com/MasamuneL/Cerberus/pull/20), merge `56f3d18`.
- `prepare`: [T1c,T1,T2,FLAIR], RAS 1 mm, lineal/NN con `grid-constant`, tolerancia 0.5 mm por esquinas,
  GTV binaria sin binarizar, `normalize_nonzero` sin GTV, recorte por soporte, restauración al grid original.
  GTV fuera de soporte/cerebro = señal de revisión. Informe siempre en `work_dir/prepare_report.json`.
- Caché `cache/<clave>/` con versiones de numpy/scipy/nibabel, sha256 por array y escritura atómica.
- `preflight`: disco/RAM estimados desde shapes. Parches 1:1 y augmentations sembradas solo en train.
- **Checks:** Ruff/formato/Pyright y 1113 tests rápidos. Revisión independiente aplicada. Probado en un
  estudio local (~7 s CPU). Sin entrenamiento. Rama `wip/FT2-preprocessing` queda obsoleta.
- Siguiente: FT3 (transferencia SegResNet y trainer).

### CP-056 · 2026-11-19 · FT3: transferencia de SegResNet y trainer reanudable

- **Integración:** [PR #21](https://github.com/MasamuneL/Cerberus/pull/21), merge `548cd16`.
- `model`: sha256 del checkpoint local (bytes leídos una vez), `weights_only=True`, `strict=True`;
  solo `conv_final.2` pasa de 3 a 1 salida con semilla fija; congelación explícita por prefijo.
- `train`: Dice+BCE con logits, AdamW, acumulación, validación con `sliding_window_inference` y Dice
  macro por paciente, parada temprana; NaN/Inf, CUDA ausente y OOM fallan claro (códigos 1/6/7/8).
- `artifacts`: `runs/<id>/` sin sobrescritura, candado, provenance, `last`/`best` atómicos.
  Reanudación k+(N-k)==N bit a bit en CPU; solo se permite subir `max_epochs`/paciencia.
- `train --dry-run` sin backward ni run. Estado global de RNG restaurado.
- **Checks:** Ruff/formato/Pyright, 1147 tests rápidos y slow de SegResNet 96³. Revisión aplicada.
  Solo datos sintéticos y pesos artificiales; sin fine-tuning real. `wip/FT3-transfer-trainer` obsoleta.
- Siguiente: FT4 (evaluación y exportación).

### CP-057 · 2026-11-19 · FT4: evaluación por paciente, baseline TC y exportación

- **Integración:** [PR #23](https://github.com/MasamuneL/Cerberus/pull/23), merge `1f85245`.
- `evaluate --run --split {val,test}`: predicción restaurada al grid original de T1c frente a la GTV
  original verificada; Dice/recall/precisión/HD95/volumen; tiempos→paciente; bootstrap por paciente.
  Umbral solo optimizable en val; test exige `--checkpoint` y registra evaluaciones previas.
- `--baseline`: TC del modelo original como referencia imperfecta (TC ≠ GTV).
- `export`: `model.pt`, `export.json` (CC BY 4.0, DOI, bloque de pesos preentrenados) y `model_card.md`;
  estado `not_evaluated`/`evaluated_val`/`evaluated_test`. `load_export` verifica hashes y kwargs.
- `cerberus_api/segmentation.py`: refactor sin cambio de comportamiento (verificado). Contratos intactos.
- **Checks:** Ruff/formato/Pyright, 1173 tests rápidos, slow segmentation/baseline. Revisión aplicada.
  Solo datos sintéticos. `wip/FT4-evaluate-export` obsoleta.
- Siguiente: FT5 (smoke offline y manual).

### CP-058 · 2026-11-19 · FT5: smoke sintético y manual — pipeline de fine-tuning construido

- **Integración:** [PR #24](https://github.com/MasamuneL/Cerberus/pull/24), merge `c891208`.
- `smoke --synthetic`: 13/13 por la CLI (validate→inventory→split→preflight→prepare→dry-run→train 2 pasos
  →resume idéntico→evaluate val/test→export→load_export) con SegResNet real, pesos artificiales, CPU,
  red bloqueada y temporal limpiado. Artefactos marcados `real_finetuning: false`.
- Manual de uso en `docs/TRAINING.md`; FT0–FT5 incorporados a `PLAN_MVP.md` §8/§9 (§6/§7 intactos).
- **Checks:** Ruff/formato/Pyright, 1180 tests rápidos, `npm run build`, `verify.mjs` 33/33 (primera
  pasada 16/19 por timeout del visor a 1440, no reproducido). Revisión independiente aplicada.
- **Definición de entrega (§10) cumplida:** comandos y artefactos existen, recorrido sintético completo,
  entradas incompatibles rechazadas, reanudación/exportación reproducibles.
- **Pendiente (no ejecutado):** auditoría del dataset completo, piloto GPU, entrenamiento real, validación
  científica, integración en API/UI y mecanismo de exclusión manual de estudios que fallen en `prepare`.
  Ramas `wip/FT*` obsoletas.

### CP-059 · 2026-11-20 · PERF1: volumetría recortada a la caja del GTV

- **Integración:** [PR #26](https://github.com/MasamuneL/Cerberus/pull/26), merge `2e50217`.
- `gtv_volumetry`: extensiones con `gtv.any(axis=…)` en lugar de `np.argwhere`; `ndi.label` sobre la caja
  del GTV + 1 vóxel; `gtv.sum()` una sola vez. Fórmulas y redondeos intactos.
- Test `test_matches_reference_implementation` (copia de la versión previa) en bordes, un vóxel,
  anisotrópico y máscara aleatoria; revisor comparó los 8 pares reales de `Data/`: 0 diferencias.
- **Benchmark** `Data/001/t0`: ~1700–1800 ms → 76–80 ms por estudio (`/volumetry`, y cada tiempo de `/longitudinal`).
- **Checks:** Ruff/formato/Pyright, 1191 tests rápidos. Revisión independiente (Opus) aprobada sin cambios.
- Siguiente: PERF2 (caché de volumetría); PERF3 y PERF5 en revisión/curso.

### CP-060 · 2026-11-20 · PERF3: predictor MONAI reutilizado entre jobs

- **Integración:** [PR #25](https://github.com/MasamuneL/Cerberus/pull/25), merge `0f882b7`.
- `_monai_predictor`: caché `_PREDICTORS` de una entrada con clave (ruta resuelta, mtime_ns, tamaño) de los
  pesos; construcción extraída a `_build_predictor(weights)`. `segresnet_predictor` (FT4) intacto.
- **Equivalencia:** máscaras TC/WT/ET bit a bit iguales entre job 1, job 2 (caché) y predictor fresco (modelo real, MPS).
- **Benchmark:** ahorra ~0.06 s por job (construcción en caliente); el job completo (~14 s) queda igual.
  Ganancia pequeña: el coste real es la inferencia. Memoria: la red (~18 MB) queda residente en el worker.
- **Checks:** Ruff/formato/Pyright, 1181 tests rápidos (rama). Revisión independiente (Opus) aprobada.
- **Desviación:** `_build_predictor` sin parámetro `device` (lo elige dentro; permite test sin torch).
- Siguiente: PERF2 y PERF5.

### CP-061 · 2026-11-20 · PERF2: caché en memoria de la volumetría

- **Integración:** [PR #28](https://github.com/MasamuneL/Cerberus/pull/28), merge `15e1e4d`.
- `gtv_volumetry` conserva firma; delega en `lru_cache(maxsize=256)` con clave (ruta resuelta, tamaño,
  mtime_ns, inode) de GTV y máscara; devuelve `model_copy()`. Reescribir un archivo (subida, `nib.save`)
  cambia la clave. El `ValueError` de GTV vacío no se cachea.
- **Benchmark** `/longitudinal` datos reales: frío 69–216 ms (ya con PERF1) → caliente 0.07–0.33 ms en la
  función y 1.4–2.9 ms por HTTP. Respuesta fría == caliente en los 5 pacientes.
- **Checks:** Ruff/formato/Pyright, 1195 tests rápidos. Revisión independiente (Opus) aprobada.
- Siguiente: PERF5 en revisión; PERF4/6/7 esperan el PR #22.

### CP-062 · 2026-11-20 · PERF5: visor cargado de forma diferida

- **Integración:** [PR #27](https://github.com/MasamuneL/Cerberus/pull/27), merge `d05c119`.
- `App.tsx`: `Viewer` con `React.lazy` + `<Suspense>`; el fallback reutiliza `.viewer-panel`/`.placeholder`
  con el texto existente «Cargando volúmenes…». Niivue solo se importa como valor en `Viewer.tsx`.
- **Benchmark build:** chunk de entrada 1,183 kB (gzip 420) → 279 kB (gzip 86.5); `Viewer-*.js` 904 kB aparte,
  sin modulepreload. Login y catálogo ya no descargan Niivue.
- **Checks:** Ruff/formato/Pyright, 1180 tests (rama), `npm run build`, `verify.mjs` 33/33. Capturas revisadas;
  fallback ejercitado con un retraso de 3 s. Revisión independiente (Opus) aprobada.
- **Pendiente (fuera de alcance):** no hay ErrorBoundary. Si falla la descarga del chunk (red caída, redeploy con
  hashes nuevos), React desmonta el Workspace. Candidato a ticket aparte.
- **Estado PERF:** PERF1/2/3/5 ✅. PERF4, PERF6 y PERF7 esperan el merge del PR #22 (VIZ1 toca `Viewer.tsx` y
  `routers/studies.py`). Siguiente: tras el merge de #22, oleada 3 (PERF4 + PERF6) y luego PERF7 según `PLAN_MVP.md` §21.

### CP-063 · 2026-11-20 · VIZ1: bordes suaves de GTV, MONAI y áreas (solo visualización)

- **Integración:** [PR #22](https://github.com/MasamuneL/Cerberus/pull/22), merge `d1edd20`.
- `cerberus_api/display.py` + `?smooth=1` en `/files/{gtv|monai_seg|brodmann}.nii.gz`: copia suavizada cacheada en
  `storage/results/<p>/<t>/display/`. Chip «Bordes suaves» (activo por defecto); GTV en gris claro; malla 3D con σ 1 mm.
  Volumetría, RANO, Dice y reportes siguen usando las máscaras originales.
- **Integración con main:** la rama era anterior a FT y PERF. Se fusionó main en la rama (`b9c76f9`). Único
  conflicto: `PLAN_MVP.md`; VIZ1 pasa a **§22** (§21 = PERF) con sus referencias de §6 y §7 actualizadas.
- **Corrección en la revisión** (`d313431`): la muestra «Superficie GTV» del panel 3D seguía en rojo; ahora usa el gris de la malla.
- **Checks del árbol fusionado:** Ruff/formato/Pyright, 1210 tests rápidos, `npm run build`, `verify.mjs` 33/33,
  `verify-mask-surface.mjs` y `verify-viewer-3d.mjs` en verde. Capturas revisadas (multiplanar con todas las capas, 3D).
- **Notas:** con el chip activo, las lecturas del cursor sobre GTV y áreas usan la copia suavizada y pueden diferir en el
  borde (documentado en el PR). La rama `feat/viz-smooth-masks` sigue viva (worktree local `../Cerberus-viz`).
- Siguiente: PERF4 + PERF6 (oleada 3); luego PERF7 y CFG1 (puertos configurables por env, pedido por el usuario).

### CP-064 · 2026-11-20 · PERF4: encolar jobs sin leer headers NIfTI

- **Integración:** [PR #29](https://github.com/MasamuneL/Cerberus/pull/29), merge `c9222d6`.
- Nuevo `catalog.find_study` (validación + `_scan` + `_make_study`), que comparte el helper `_find_files` con
  `get_study`. Lo usan `start_segmentation`, `start_area_mapping`, `worker.segment_study` y `worker.map_areas`.
  `GET /studies/{p}/{t}` sigue con `get_study`.
- **Benchmark** 001/t0: 10.7–13.3 ms → 0.22–0.52 ms por búsqueda. Equivalencia comprobada en los 8 estudios reales.
- **Desviaciones:** un NIfTI con header corrupto ya no da 500 al encolar; falla en el job (`failed`). `get_study` reutiliza
  `_find_files` y no `find_study`, porque necesita las rutas.
- **Checks:** Ruff/formato/Pyright, 1213 tests rápidos. Revisión independiente (Opus) aprobada.
- **Pendiente (fuera de alcance):** `routers/uploads.py` `_find_study` recorre `list_studies` entero; podría usar `find_study`.

### CP-065 · 2026-11-20 · CFG1: puertos configurables por entorno

- **Integración:** [PR #30](https://github.com/MasamuneL/Cerberus/pull/30), merge `c491be1`.
- `Settings`: `api_host` (127.0.0.1), `api_port` (8000) y `ui_port` (5173), con rango 1–65535. `cors_origins` y
  `app_origin` se derivan de `ui_port` solo si no se fijaron (`model_fields_set`). No se leen archivos `.env`.
- Nuevo lanzador `uv run python -m cerberus_api.serve [--reload]`; `uvicorn … --port 8000` sigue funcionando.
- `vite.config.ts` lee `CERBERUS_UI_PORT` y `CERBERUS_API_PORT` (para el proxy). Los scripts de `tools/e2e` usan
  `CERBERUS_UI_PORT` por defecto, y `verify-docker.mjs` usa `CERBERUS_HTTP_PORT`.
- Docs: README (desarrollo, con Redis en otro puerto), `AGENTS.md` (Comandos), `PLAN_MVP.md` §5 y §23.
- **Equivalencia:** sin variables, `Settings().model_dump()` y la config de Vite son idénticos a main. Docker no cambia
  (CORS y APP_ORIGIN explícitos).
- **Prueba manual:** API 8011/8012 y UI 5191/5192; `/api/health` responde a través del proxy.
- **Checks:** Ruff/formato/Pyright, 1219 tests rápidos, `npm run build`. Revisión independiente (Opus) aprobada.
- **Nota menor:** en Vite, un `CERBERUS_UI_PORT` vacío o no numérico da 0/NaN; la API sí lo rechaza.

### CP-066 · 2026-11-20 · PERF6: caché de buffers del visor por estudio

- **Integración:** [PR #31](https://github.com/MasamuneL/Cerberus/pull/31), merge `80dc618`.
- `Viewer.tsx`: `fetchVolumeCached` con un `Map` por estudio de los buffers comprimidos de las URLs sin `v=` (base y GTV crudo/`?smooth=1`).
  Límites: 1 base + 2 variantes de GTV, 128 MB por buffer. `monai_seg`/`brodmann` siempre van a la red. No se cachean errores.
  Niivue 0.69.0 no transfiere ni muta el buffer (verificado en `dist/index.js:32807, 24864, 25008`).
- Nuevo `tools/e2e/verify-overlay-toggle.mjs`: tras 4 toggles (GTV y «Bordes suaves»), GET de la base 4 → **0**; GTV 3 → 1.
- **Medición honesta:** como la API ya respondía 304 (ETag + `no-cache`), el tiempo por toggle sin carga concurrente es igual
  antes y después (~15–25 s con SwiftShader; domina la re-decodificación). La ganancia es menos peticiones y menos revalidación,
  no menos tiempo de interfaz. Para bajar ese tiempo habría que reutilizar el `NVImage` decodificado (opción B, no hecha).
- **Checks:** Ruff/formato/Pyright, 1210 tests, `npm run build`, e2e `verify` 33/33, `viewer-3d` 7/7, `mask-surface` 3/3,
  `overlay-toggle` 4/4. Capturas revisadas. Revisión independiente (Opus) aprobada.
- Siguiente: PERF7 (centroide del GTV).

### CP-067 · 2026-11-20 · PERF7: centroide del GTV sin división por vóxel

- **Integración:** [PR #32](https://github.com/MasamuneL/Cerberus/pull/32), merge `e01ea78`.
- `computeGtvCentroidMM`: tres bucles anidados z→y→x con un índice lineal; sin `%` ni `Math.floor` por vóxel.
- **Equivalencia:** bit a bit en 2009 casos (8 bordes, 2000 máscaras aleatorias y el GTV real 001/t0, 0 fallos);
  `crosshairPos` idéntica en el navegador.
- **Benchmark** (navegador, 001/t0, 54.5 M vóxeles): ~39 → 31 ms (−19 %). El coste dominante es recorrer el volumen.
- **Checks:** Ruff/formato/Pyright, 1222 tests, `npm run build`, `verify.mjs` 33/33. Revisión independiente (Opus) aprobada.
- **Plan PERF completo:** PERF1–PERF7 ✅ (CP-059–067), con VIZ1 (CP-063) y CFG1 (CP-065) integrados en la misma sesión.

### CP-068 · 2026-11-20 · CFG2: Vite valida los puertos del entorno

- **Integración:** [PR #33](https://github.com/MasamuneL/Cerberus/pull/33), merge `bb8be2f`. Cierra la nota menor de CP-065.
- `frontend/vite.config.ts`: `parsePort(name, fallback)` para `CERBERUS_UI_PORT` y `CERBERUS_API_PORT`. Ausente → default;
  presente debe casar `^\d+$` y estar en 1–65535, si no Vite sale con «<VAR> debe ser un entero entre 1 y 65535 (recibido: "…")».
- **Equivalencia:** sin variables, `loadConfigFromFile` da `{port: 5173, proxy: {"/api": "http://localhost:8000"}}` en main y en la rama.
- **Pruebas manuales:** `""`, `abc`, `0`, `70000`, `5.5`, `-1`, `1e3`, `65536`, `" 5197"` → exit 1; 5191/5197 arrancan y el proxy
  responde; `CERBERUS_API_PORT=9` → 502 (el proxy usa la variable).
- **Desviación:** antes un valor inválido arrancaba en un puerto aleatorio/NaN; ahora falla al arrancar. Un espacio inicial
  se rechaza (la API probablemente lo aceptaría).
- **Checks:** Ruff/formato/Pyright, 1222 tests, `npm run build`. Revisión independiente (Opus) aprobada.
- Siguiente: UP1 en revisión (PR #34), PERF8 midiendo el gate; luego ERR1.

### CP-069 · 2026-11-20 · UP1: las subidas resuelven el estudio con `find_study`

- **Integración:** [PR #34](https://github.com/MasamuneL/Cerberus/pull/34), merge `8f02a18`. Cierra el pendiente de CP-064.
- `routers/uploads.py`: se elimina `_find_study` (recorría `list_studies`); `_study_or_500` llama a `catalog.find_study`.
- **Equivalencia:** mismo `_scan` + `_make_study`, solo cambia el glob (`<p>/<t>/*.nii.gz`); ausente/vacío → `None` → mismo 500.
  Tests: el `Study` de subida y confirm es `==` al de `list_studies` filtrado; con `list_studies` parcheado para lanzar, siguen dando 201.
- **Benchmark** 001/t0 (8 estudios): 0.64 → 0.08 ms. **Marginal**: una llamada por subida; crece con el catálogo.
- **Checks:** Ruff/formato/Pyright, 1224 tests rápidos. Revisión independiente (Opus) aprobada.
- Siguiente: PERF8 (gate de medición) y ERR1.

### CP-070 · 2026-11-20 · PERF8 descartado por el gate de medición

- **Sin integración:** no hubo commit ni PR; rama y worktree borrados. Decisión del usuario: descartar y anotar.
- **Medición** (001/t0, base `t1gd` con GTV, MONAI y áreas, Chrome headless + SwiftShader, mediana de 3 corridas, instrumentación
  temporal no commiteada):

| Toggle | Total (ms) | Descarga + decodificación (ms) | Decodificación ahorrable (ms) | Ahorrable / total |
|---|---|---|---|---|
| ocultar GTV | 16112 | 1277 | 782 | 4.9 % |
| mostrar GTV | 27193 | 1105 | 1266 | 5.1 % |
| bordes suaves off | 26205 | 1325 | 566 | 2.3 % |
| bordes suaves on | 26236 | 1088 | 1208 | 4.9 % |

- Aunque se eliminara toda la etapa de descarga y decodificación, el toggle bajaría como mucho ~1–1.3 s (≤ 8 %). El ~92 % está
  después: `nv.volumes = []`, `addVolume` × N (cada uno refresca capas GL), `setOpacity`, `setColormapLabel` + `updateGLVolume`,
  `setSliceType` y el render.
- **Pendiente nuevo (hipótesis no medida):** agrupar los refrescos GL en un solo `updateGLVolume` por lote, o alternar capas con
  opacidad 0 sin recargar. Antes de un ticket, perfilar ese ~92 % por llamada. Con GPU real (no SwiftShader) el reparto puede cambiar.
- Siguiente: ERR1 en curso.

### CP-071 · 2026-11-20 · HW4: modo híbrido macOS Apple Silicon

- **Integración:** [PR #35](https://github.com/MasamuneL/Cerberus/pull/35), merge `b3512c1`. Fallback: tag `pre-HW4`
  (main antes del merge) y `git revert -m 1 b3512c1`.
- `compose.hybrid.yaml`: el worker de Docker queda bajo el perfil `docker-worker` (no arranca por defecto) y Redis se
  publica solo en `127.0.0.1:${CERBERUS_REDIS_PORT:-6379}`. El worker corre nativo (`uv run`) con MPS y ANTs arm64
  sobre los mismos `Data/`, `storage/` y `models/`. README: sección «Mac Apple Silicon: modo híbrido».
- `backend/tests/test_compose_hybrid.py` (4 tests de `docker compose config`, sin daemon ni red; se saltan sin Compose v2).
- **Medido en 001/t0** (Mac arm64 con carga alta de otras sesiones, 2 corridas): segmentación 16–34 s nativo contra
  87–90 s en Docker+Rosetta; áreas en frío 26–38 s contra 67–70 s; con caché de registro 9 s contra 31 s.
- **Checks:** Ruff/formato/Pyright, 1228 tests tras traer main. Revisión independiente (Opus) aprobada; sus 2 nits aplicados.
- En curso: HW1 (CUDA) y HW3 (PR #36, en revisión). Hallazgo de HW3: el registro `full` no es determinista entre
  corridas (004/t0, Dice 0.18 contra sí mismo); ticket aparte por definir.

### CP-072 · 2026-11-20 · HW3: registro ANTs `full`/`fast` para áreas de Brodmann

- **Integración:** [PR #36](https://github.com/MasamuneL/Cerberus/pull/36), merge `f1f432a`. Fallback: tag `pre-HW3`
  y `git revert -m 1 f1f432a`.
- `CERBERUS_REGISTRATION=full|fast` (default `full`, validado en `Settings.registration`; llega a API y worker en
  `compose.yaml`). `full` es bit a bit el de antes: mismos kwargs de `ants.registration` y misma huella de caché, así
  que las cachés existentes siguen valiendo. `fast` = SyN `(20,10,0)` con imagen móvil **y plantilla MNI** a 2 mm.
  Cada modo tiene su caché y su directorio (`mni/` y `mni_fast/`). `registration` termina en «(rápido)».
- **Benchmark** (en frío, 2 corridas, máquina con carga alta): 001/t0 31.8/27.6 → 10.8/9.5 s (2.9×); 004/t0 3.0×;
  005/t1 2.6×. `antsRegistrationSyNQuick[s]` salió más lento (0.61×) y se descartó.
- **Calidad:** en 001/t0 las «Afectadas» con solape ≥ 0.5 cm³ son idénticas. En 005/t1 solo falta un área de 0.0 cm³.
  En 004/t0 la comparación no es válida: `full` no coincide consigo mismo (Jaccard 0.59). El criterio se enmendó en §25.
- **Revisión** (Opus): CAMBIOS → APROBADO. Se aplicaron B1 (tipado de los spies en tests; pyright no se había corrido
  bien sobre el worktree) y R1 (un directorio `mni` por modo).
- **Hallazgo → REG1** (§25): el registro `full` no es determinista con varios hilos. En 004/t0 la etapa afín cae en
  mínimos distintos (Dice 0.18). La caché lo oculta, pero cualquier re-registro puede cambiar el reporte de áreas.
- **Checks:** Ruff/formato/Pyright, 1237 tests tras traer main.
- En curso: HW1 (CUDA). Luego HW2 (lanzador) y REG1.

### CP-073 · 2026-11-21 · ERR1: ErrorBoundary con reintento para el visor diferido

- **Integración:** [PR #37](https://github.com/MasamuneL/Cerberus/pull/37), merge `84cc549`. Cierra el pendiente de CP-062 y el plan §24.
- Nuevo `ViewerErrorBoundary` (clase): alerta «No se pudo cargar el visor.» + «Reintentar» dentro de `.viewer-panel`.
  `App.tsx`: factoría `loadViewer()` (un `lazy` nuevo por reintento, porque React cachea el import rechazado), `key` por estudio.
  El `SidePanel` queda fuera del boundary y sigue montado. También captura errores de render del `Viewer`.
- **Desviación (justificada en la revisión):** al reintentar, `reloadFailedStylesheets()` clona los `<link rel=stylesheet>` fallidos.
  El helper de preload de Vite 8.3.5 (`dist/node/chunks/node.js:27006-27084`) no vuelve a pedir un CSS fallido y el visor salía sin
  estilos en el build. En dev no hace nada (el CSS va en `<style>`). La detección se basa en Chrome (`SecurityError` en `cssRules`).
- **Sin errores nada cambia:** el `key` no remonta más que antes (`setDetail(null)` ya desmontaba al cambiar de estudio).
  Entrada 86.50 → 86.74 kB gzip; chunk del visor igual.
- Nuevo `tools/e2e/verify-viewer-chunk-error.mjs`: 5/5 en dev y en `vite preview`. `verify.mjs` 33/33. axe sin violaciones en el fallback.
- **Checks:** Ruff/formato/Pyright, 1224 tests, `npm run build`. Revisión independiente (Opus) aprobada.
- **Notas menores (no hechas):** el botón «Reintentar» sale sin estilo y a todo el ancho (`.btn-secondary` solo existe dentro de
  `.upload-panel`); tras un reintento fallido el foco cae a `<body>`. El trailer del commit `04835ef` dice Sonnet 5.5 en vez de Opus 5.5.
- **Plan §24 cerrado:** CFG2, UP1 y ERR1 ✅; PERF8 descartado por el gate (CP-070).

### CP-074 · 2026-11-21 · HW1: imagen CUDA y perfil GPU NVIDIA

- **Integración:** [PR #38](https://github.com/MasamuneL/Cerberus/pull/38), merge `9ee6bc3`. Fallback: tag `pre-HW1`
  y `git revert -m 1 9ee6bc3`.
- torch pasa a dos grupos excluyentes, `torch-cpu` (por defecto) y `torch-cu126` (`[tool.uv] conflicts`). `uv sync` local
  y la imagen CPU no cambian (freeze y md5 de `site-packages/torch` idénticos). Dockerfile `ARG TORCH_VARIANT=cpu|cu126`.
  `compose.gpu.yaml`: worker con `cerberus-backend:cuda` y reserva NVIDIA. La imagen CUDA pesa 7.29 GB; la CPU, 1.5 GB.
- **Por qué cu126:** torch 2.14.1 se publica en cpu, cu126, cu130 y cu132. cu126 admite drivers ≥ 525 y trae kernels sm_50–sm_90.
- `segmentation.py`: fp16 (`autocast`) solo en CUDA. La salida de la ventana deslizante queda en RAM. Ante OOM (incluidos
  los `RuntimeError` «out of memory») se repite en CPU con aviso. FT4 sigue en fp32.
- `runtime.arch_supported`: una GPU sin kernels en la rueda (p. ej. RTX 50xx sm_120 con cu126) usa CPU con aviso, en vez de
  fallar cada job. `SystemInfo.gpu_name` y `gpu_memory_gb` (opcionales; §7/§16, `types.ts`). La UI muestra «GPU NVIDIA (nombre, N GB)».
- **Medido en Mac arm64:** máscaras de CPU y MPS bit a bit iguales a main; MPS ~11–15 s.
- **Revisión** (Opus): CAMBIOS → APROBADO. B1: un `uv run` sin flags reinstalaba torch CPU y el test CUDA se saltaba.
  B2: fallback por arquitectura. También se aplicaron los recomendados.
- **Pendiente:** validar en la PC NVIDIA con `CERBERUS_REQUIRE_CUDA=1 uv run --no-group torch-cpu --group torch-cu126 pytest -m slow -k cuda_fp16 -s`
  y `docker stats` (¿bastan 6g de `mem_limit` con CUDA?). Para HW2: variante cu130 para Blackwell y ajuste de memoria.
- **Checks:** Ruff/formato/Pyright, 1272 tests, `npm run build`.
- Siguiente: HW2 (lanzador). Después, REG1.

### CP-075 · 2026-11-21 · HW2: lanzador con detección de hardware + variante cu130

- **Integración:** [PR #39](https://github.com/MasamuneL/Cerberus/pull/39), merge `f68173b`. Fallback: tag `pre-HW2`
  y `git revert -m 1 f68173b`.
- `tools/launch/up.sh` (macOS/Linux/WSL2, bash 3.2+) y `up.ps1` (PowerShell 5.1+/7). Detectan SO, arquitectura,
  CPU/RAM de Docker y NVIDIA, y eligen el modo:
  - NVIDIA → `compose.gpu.yaml` con cu126, o cu130 si cc ≥ 10.0 y driver ≥ 580; con driver viejo, CPU con aviso.
  - darwin/arm64 → modo híbrido con el worker nativo (PID y log en `storage/launch/`).
  - arm64 con NVIDIA fuera del híbrido → ignora la GPU.
  - Resto → `compose.yaml`.
- Fija `CERBERUS_WORKER_MEM_LIMIT = clamp(RAM Docker − 2, 5, 12 GB)` (mínimo 6 con GPU) y `CERBERUS_UID/GID` en
  Linux/WSL2, y sugiere `--fast` con ≤ 4 CPU o emulación. Nunca pisa variables del entorno ni del `.env`.
  Opciones: `--dry-run`, `--cpu`, `--no-hybrid`, `--fast`, `--foreground`, `down`.
- Grupo `torch-cu130` (índice cu130). La imagen CPU y `uv sync` local no cambian (exports idénticos a main).
- `MAX_AUTO_THREADS` se queda en 8: las áreas ganan 12–19 % con 12–14 hilos solo con poca carga (n = 2), dentro del
  ruido. Además, más hilos empeoran la reproducibilidad del afín (REG1).
- **Prueba real (Mac arm64):** el stack híbrido arrancó en 46 s con `/api/system` = darwin/arm64, mps,
  `in_container: false`, y `down` lo bajó limpio.
- **Revisión** (Opus): CAMBIOS → APROBADO.
  - B1: `$VAR»` rompía bash 3.2 con UTF-8.
  - R1–R11 aplicados: código de salida de `nvidia-smi`, arm64+NVIDIA, límites de subida al worker nativo,
    TERM en `up.ps1 down`, validación del PID, `uv sync --locked`.
- **Checks:** shellcheck, `bash -n` (5 y 3.2), Ruff/formato/Pyright, 1310 tests.
- **Pendiente manual:**
  - `up.ps1` no se ha ejecutado nunca: en Windows, correr `--dry-run` e `Invoke-ScriptAnalyzer`.
  - Validar en la PC NVIDIA (CP-074) y probar cu130 en una Blackwell.
- **Plan §25:** HW1–HW4 ✅. Queda REG1.

