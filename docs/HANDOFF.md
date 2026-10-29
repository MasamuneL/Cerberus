# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-10-29 · último checkpoint: CP-025 · rama de trabajo: `feature/ux-ui`

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
B12 (dominios funcionales, §14) y F11 (tipografía, tokens AA y lista de estudios, §14).

**En curso: §14 · Mejoras de UX/UI** (ver la spec completa en `PLAN_MVP.md` §14).

| Ticket | Estado | Qué falta |
|---|---|---|
| F9 · panel de capas + paleta fría + barra del cursor + atajos | 🟡 implementación recuperada de Claude; revisión y QA en curso | Capas fuera del canvas; comprobar lectura, atajos y opacidades durante cargas |
| F10 · pestañas + "Funciones en riesgo" + tabla accesible | 🟡 implementación recuperada de Claude; revisión y QA en curso | Botones nativos en las filas; etapas del job sin progreso ficticio |

**Continuación con Codex, a petición del usuario:** trabajar y subir exclusivamente a **`feature/ux-ui`**;
no integrar a `main` durante esta tarea. CP-025 respalda la implementación heredada y las primeras correcciones.
El respaldo anterior de Claude sigue en `wip/ux-14`.

**Verificación hasta CP-025:** frontend build correcto; ruff y formato correctos; pyright sin errores;
pytest rápido: **425 passed, 5 deselected**. El QA antiguo falla porque intenta desmarcar un checkbox que ahora
es un botón `aria-pressed`. Se está actualizando `tools/e2e/verify.mjs` con Playwright y axe, fallos con exit 1,
capturas a 1440×900 y 1280×800, teclado, riesgos y jobs simulados sin ejecutar MONAI/ANTs.

**Trabajo repartido (solo contexto de esta sesión):** `viewer_f9` revisa el visor y sus componentes;
`sidepanel_f10` revisa los paneles; `qa` actualiza `tools/e2e/`; el orquestador integra, documenta y sube.
Notas temporales de recuperación en `/private/tmp/cerberus-{viewer-f9,sidepanel-f10,qa}.md`, si existen;
el estado durable es esta rama y estos documentos.

### Cómo terminar §14 si retomas tú
1. `git fetch && git checkout feature/ux-ui && git pull --ff-only` (si no existe localmente:
   `git checkout -b feature/ux-ui origin/feature/ux-ui`).
2. `cd frontend && npm install && npm run build`. Corrige los errores respetando la propiedad de archivos de
   la tabla de arriba.
3. Cumple los criterios de §14 en `PLAN_MVP.md`. Lo crítico:
   - Las áreas **nunca** usan rojo, naranja ni amarillo (los hues de 0–60° y 330–360° quedan reservados para el tumor).
   - "Funciones en riesgo": 🔴 un área elocuente se solapa con el GTV · 🟠 se solapa sin ser elocuente, o es elocuente a ≤ 5 mm ·
     🟡 está a ≤ 10 mm. La severidad se marca con icono y texto, no con los colores del tumor.
   - Accesible por teclado (pestañas con flechas, filas con Enter), `aria-pressed` en los toggles y contraste AA.
4. Verifica con `tools/e2e` en 1440×900 y 1280×800 y **revisa las capturas**.
5. Termina los fixes de F9/F10, corre el QA actualizado y revisa las PNG. Registra resultados y limitaciones
   en `PROGRESS.md` y este archivo. Haz commit y push a `feature/ux-ui`; el merge a `main` queda pendiente.

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
