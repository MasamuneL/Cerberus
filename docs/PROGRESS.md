# PROGRESS — Cerberus MVP

Fuente de verdad del avance. Protocolo en [`PLAN_MVP.md` §12](PLAN_MVP.md#12-checkpoints-y-trazabilidad-entre-dispositivos).
Leyenda: ⬜ pendiente · 🟡 en curso · ✅ hecho · ⛔ bloqueado.

## Tablero

| Ticket | Estado | Rama | Commit | Fecha | Responsable / herramienta | Notas |
|---|---|---|---|---|---|---|
| B0 · Bootstrap | ✅ | feat/B0-bootstrap | 31d619a | 2026-10-27 | Vikingo / Claude Code (orquestador) | |
| B1 · config + sequences | ✅ | feat/B1-config-sequences | bad8563 | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B2 · catalog | 🟡 | feat/B2-catalog | | 2026-10-27 | Vikingo / Claude Code (subagente) | depende de B1 |
| B3 · volumetry | 🟡 | feat/B3-volumetry | | 2026-10-27 | Vikingo / Claude Code (subagente) | depende de B1 |
| B4 · API de lectura | ⬜ | | | | | depende de B2, B3 |
| B5 · segmentation | ⬜ | | | | | depende de B2 |
| B6 · jobs | ⬜ | | | | | depende de B4, B5 |
| B7 · subida NIfTI | ⬜ | | | | | depende de B4 |
| B8 · ingesta DICOM | ⬜ | | | | | depende de B6, B7 |
| F0 · Scaffold | ✅ | feat/F0-scaffold | 8aa033a | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F1 · API client | ✅ | feat/F1-api-client | d40323f | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F2 · StudyList | ⬜ | | | | | depende de F1, B4 |
| F3 · Viewer | ⬜ | | | | | depende de F1, B4 |
| F4 · VolumetryPanel | ⬜ | | | | | depende de F1, B4 |
| F5 · SegmentationPanel | ⬜ | | | | | depende de F3, B6 |
| F6 · UploadPanel | ⬜ | | | | | depende de F1, B7, B8 |
| D1 · README | ⬜ | | | | | al final |
| E2E · Verificación §10 | ⬜ | | | | | al final |

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
