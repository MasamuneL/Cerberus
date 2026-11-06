# AGENTS.md — Cerberus

Instrucciones para cualquier agente de código (Codex, Claude Code, Cursor, Copilot…) y para humanos.

## Qué es Cerberus

App web para explorar, medir y segmentar glioblastoma sobre el dataset CFB-GBM (TCIA).
Backend FastAPI + arq/Redis + MONAI; frontend React + Vite + TypeScript + Niivue.

**Fuente de verdad del alcance, contratos y tickets: [`docs/PLAN_MVP.md`](docs/PLAN_MVP.md).**
Léelo antes de escribir código. Las secciones §6 (disco) y §7 (API) son contratos.

`cerberus_eda.py` (notebook marimo) es la implementación de referencia de las fórmulas: volumetría, RANO,
Dice y MONAI. No lo modifiques; porta su lógica.

## Comandos

```bash
uv sync                                                    # deps Python (incluye el paquete en modo editable)
redis-server                                               # terminal 1
uv run python -m cerberus_api.worker              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --port 8000  # terminal 3: API (docs en /docs)
cd frontend && npm install && npm run dev                  # terminal 4: UI en :5173

# Checks obligatorios antes de un PR
uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -m "not slow"
cd frontend && npm run build                               # tsc -b && vite build
```

Tests lentos (modelo real y dcm2niix real): `uv run pytest -m slow`.

## Flujo de trabajo

0. **Antes de nada:** `git pull` y lee [`docs/HANDOFF.md`](docs/HANDOFF.md) (estado vivo y trabajo a medias) y
   [`docs/PROGRESS.md`](docs/PROGRESS.md) (tablero + último checkpoint).
   Protocolo completo en `docs/PLAN_MVP.md` §12.
1. Elige **un** ticket de `docs/PLAN_MVP.md` §8 cuyas dependencias ya estén en `main` (ver §9).
2. Crea la rama `feat/<ID>-<slug>` (ej. `feat/B3-volumetry`).
3. Implementa **solo** ese ticket. Si ves algo fuera de alcance, anótalo en el PR; no lo hagas.
4. Corre los checks de arriba hasta que pasen.
5. Abre un PR pequeño con el ID del ticket en el título y lista los criterios de aceptación cumplidos.
6. **Checkpoint:** tras el merge, actualiza `docs/PROGRESS.md` (ticket ✅ + entrada `CP-NNN`) **y** la sección 2 de
   `docs/HANDOFF.md`, y haz push. Si dejas trabajo a medias, súbelo a una rama `wip/<tema>` y anótalo en el handoff.
7. **Verificación visual:** `cd tools/e2e && npm install && node verify.mjs` y revisa las capturas.

## Reglas

1. **Contratos:** no cambies §6 o §7 del plan sin actualizar `backend/cerberus_api/schemas.py`,
   `frontend/src/api/types.ts` y `docs/PLAN_MVP.md` en el mismo PR.
2. **Python:** solo `uv add` / `uv run`. Nunca `pip install`.
3. **No commitear:** `Data/` (salvo `Data/001`, que va por Git LFS), `models/`, `storage/`, `.env` ni secretos.
4. **Datos personales (DICOM), sin excepciones:**
   - El DICOM crudo solo vive en `storage/tmp/` y se borra en un `finally`.
   - El manifest y los logs nunca guardan `PatientName`, `PatientID`, `PatientBirthDate`, `InstitutionName`,
     `AccessionNumber`, `StudyDate` ni UIDs DICOM.
   - dcm2niix siempre con `-b n -f series`.
5. **Fórmulas:** reutiliza las del notebook. En el docstring cita el rango portado (ej. "Portado de `cerberus_eda.py:209-235`").
6. **Tests:** cada función nueva del backend lleva tipos y al menos un test. Los tests no usan red; MONAI se
   mockea con el parámetro `predictor`. Los tests pesados se marcan `@pytest.mark.slow`.
7. **Idioma:** identificadores en inglés; comentarios, docs y textos de la UI en español. Sigue el estilo y la
   densidad de comentarios del notebook.
8. **APIs de librerías:** no inventes firmas. Verifícalas en el código instalado (`.venv/`,
   `frontend/node_modules/`, sobre todo Niivue y arq). Si el plan choca con la realidad, adapta y explícalo en el PR.
9. **Seguridad de rutas:** valida `patient`, `timepoint`, `sequence` y los nombres de archivo con
   `cerberus_api.sequences` **antes** de construir cualquier `Path`.
10. **NIfTI tipado:** en el backend usa `cerberus_api.nifti.load_nifti()` en lugar de `nib.load()`, porque pyright
    tipa `nib.load` como `FileBasedImage`.
11. **Terminología:** la máscara del dataset es **GTV** (excluye edema). No la llames "tumor" en la UI.

## Definición de hecho

- Se cumplen los criterios de aceptación del ticket.
- Pasan los checks de arriba.
- Docs actualizadas si cambió algo de §5–§7 del plan o de los comandos.
- Checkpoint registrado en `docs/PROGRESS.md` y pusheado.
