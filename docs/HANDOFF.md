# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-10-29 · último checkpoint: CP-023 · rama base: `main`

## 1. Arranque rápido

```bash
git checkout main && git pull && git lfs pull
uv sync && (cd frontend && npm install)
redis-server                                                    # terminal 1
uv run arq cerberus_api.worker.WorkerSettings                   # terminal 2
uv run uvicorn cerberus_api.main:app --reload --reload-dir backend --port 8000   # terminal 3
cd frontend && npm run dev                                      # terminal 4 (:5173; si está ocupado: npx vite --port 5180 --strictPort)
```

Checks antes de cualquier commit (§5 del plan):
```bash
uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -q -m "not slow"
cd frontend && npm run build
```

Verificación visual (Playwright con Chrome instalado, headless):
```bash
cd tools/e2e && npm install && CERBERUS_UI=http://localhost:5173 node verify.mjs   # capturas en tools/e2e/shots/
```
Abre las PNG y revísalas: **no te fíes solo de los ✅**. Leer píxeles del canvas WebGL devuelve negro
(`preserveDrawingBuffer=false`), así que esos chequeos de píxeles no son confiables.

## 2. Estado actual

**Terminado y en `main`:** el MVP completo (B0–B8, F0–F6, D1, E2E), las áreas de Brodmann (§13: B9–B11, F7, F8) y
B12 (dominios funcionales, §14).

**En curso: §14 · Mejoras de UX/UI** (ver la spec completa en `PLAN_MVP.md` §14).

| Ticket | Estado | Qué falta |
|---|---|---|
| F9 · panel de capas + paleta fría + barra del cursor + atajos | 🟡 lo implementa un subagente | `Viewer.tsx`, `areaColors.ts`, `components/viewer.css` y `components/viewer/` |
| F10 · pestañas + "Funciones en riesgo" + tabla accesible | 🟡 lo implementa un subagente | `App.tsx`, `SidePanel.tsx`, `RiskSummary.tsx`, `AreasPanel.tsx`, `VolumetryPanel.tsx`, `sidepanel.css` |
| F11 · tipografía Plex + tokens/contraste AA + lista de estudios | 🟡 lo implementa un subagente | `main.tsx`, `styles.css`, `StudyList.tsx`, `package.json` (`@fontsource/*`) |

**Trabajo sin commit:** si el árbol tiene cambios en `frontend/` que no están en `main`, son de F9–F11. Hay una
foto del trabajo en curso en la rama **`wip/ux-14`** (puede no compilar; es solo para no perderlo).

### Cómo terminar §14 si retomas tú
1. `git fetch && git checkout -b feat/ux-14 origin/wip/ux-14` (o parte de `main` si ya se integró algo).
2. `cd frontend && npm install && npm run build`. Corrige los errores respetando la propiedad de archivos de
   la tabla de arriba.
3. Cumple los criterios de §14 en `PLAN_MVP.md`. Lo crítico:
   - Las áreas **nunca** usan rojo, naranja ni amarillo (los hues de 0–60° y 330–360° quedan reservados para el tumor).
   - "Funciones en riesgo": 🔴 un área elocuente se solapa con el GTV · 🟠 se solapa sin ser elocuente, o es elocuente a ≤ 5 mm ·
     🟡 está a ≤ 10 mm. La severidad se marca con icono y texto, no con los colores del tumor.
   - Accesible por teclado (pestañas con flechas, filas con Enter), `aria-pressed` en los toggles y contraste AA.
4. Verifica con `tools/e2e` en 1440×900 y 1280×800 y **revisa las capturas**.
5. Haz un commit por ticket (`feat(F9): …`, `feat(F10): …`, `feat(F11): …`), merge a `main`, escribe el checkpoint
   CP-0NN en `PROGRESS.md`, actualiza este archivo y haz push.

## 3. Lecciones aprendidas (léelas, ahorran horas)
- **Niivue `scene.crosshairPos` es una fracción 0–1, no mm.** Para centrar: vóxel (orden del archivo) → mm con
  `vol.hdr.affine` (4×4 por filas) → `nv.mm2frac(mm)`. `vox2frac` usa `dimsRAS` (volumen reorientado) y no sirve
  con índices de `vol.img`. Ver `centerCrosshairOnGtv` en `Viewer.tsx`.
- **Si cambias `schemas.py`, reinicia la API y el worker.** Sin recarga, el `response_model` viejo descarta campos
  nuevos sin avisar (pasó con `domains`).
- Git LFS: la regla `*.ts` es solo `models/**/*.ts` (TorchScript). Nunca la vuelvas global: metería el TypeScript en LFS.
- El puerto 5173 puede estar ocupado por otro proyecto en la máquina del autor; usa `--port 5180 --strictPort`.
- ANTs no es 100 % determinista con varios hilos: los vóxeles por área varían ±3 % entre corridas.
- Atlas Talairach `ba`: etiqueta corteza gris y núcleos, no sustancia blanca. "% del área" = fracción de esa corteza
  etiquetada dentro del GTV.
- Un subagente o IA puede reportar éxito sin haberlo logrado (pasó en F8). Verifica siempre con capturas.

## 4. Siguiente después de §14 (propuesto, sin aprobar)
Reporte exportable por estudio (PDF o imprimible), 3D más limpio (iluminación y orientación), subir archivos
arrastrándolos, atajos extra. Fase 2 pendiente: auth, skull-strip (HD-BET o SynthStrip) para DICOM sin
`brain_mask`, registro entre series, RTSTRUCT y Docker.

## 5. Protocolo de handoff (para quien trabaje, humano o IA)
- En **cada** checkpoint actualiza la sección 2 de este archivo (estado, trabajo en curso, siguiente paso) en el mismo
  commit que `PROGRESS.md`.
- Si vas a dejar trabajo a medias, súbelo a `wip/<tema>` (aunque no compile) y anótalo aquí.
- Nunca dejes en tu máquina, sin subir, lo único que alguien necesita para continuar.
