# PROGRESS — Cerberus MVP

Fuente de verdad del avance. Protocolo en [`PLAN_MVP.md` §12](PLAN_MVP.md#12-checkpoints-y-trazabilidad-entre-dispositivos).
Leyenda: ⬜ pendiente · 🟡 en curso · ✅ hecho · ⛔ bloqueado.

## Tablero

| Ticket | Estado | Rama | Commit | Fecha | Responsable / herramienta | Notas |
|---|---|---|---|---|---|---|
| B0 · Bootstrap | ✅ | feat/B0-bootstrap | 31d619a | 2026-10-27 | Vikingo / Claude Code (orquestador) | |
| B1 · config + sequences | 🟡 | feat/B1-config-sequences | | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| B2 · catalog | ⬜ | | | | | depende de B1 |
| B3 · volumetry | ⬜ | | | | | depende de B1 |
| B4 · API de lectura | ⬜ | | | | | depende de B2, B3 |
| B5 · segmentation | ⬜ | | | | | depende de B2 |
| B6 · jobs | ⬜ | | | | | depende de B4, B5 |
| B7 · subida NIfTI | ⬜ | | | | | depende de B4 |
| B8 · ingesta DICOM | ⬜ | | | | | depende de B6, B7 |
| F0 · Scaffold | 🟡 | feat/F0-scaffold | | 2026-10-27 | Vikingo / Claude Code (subagente) | |
| F1 · API client | ⬜ | | | | | depende de F0 |
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
