# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-10-29 · último checkpoint: CP-030 · rama base: `main`

## 1. Arranque rápido

```bash
git checkout main && git pull --ff-only && git lfs pull
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
B12 (dominios funcionales, §14) y F9–F11 (UX/UI, tipografía y accesibilidad, §14).

**§14 completo e integrado en `main`.** El [PR #1](https://github.com/MasamuneL/Cerberus/pull/1)
se fusionó el 2026-10-29 a las 17:49:18 UTC: merge `bcef409`.

| Ticket | Estado | Resultado |
|---|---|---|
| F9 · capas + paleta fría + cursor + atajos | ✅ | Capas fuera del canvas, opacidad estable durante cargas, lectura de cursor, atajos y fondo transparente en «Todas» |
| F10 · pestañas + funciones en riesgo + tabla accesible | ✅ | Pestañas y filas con teclado, severidad por dominio, tablas sin desborde y etapas sin progreso ficticio |

**QA final (CP-027):** `CERBERUS_UI=http://localhost:5180 npm run verify` terminó con exit 0 el
2026-10-29 a las 17:43:15 UTC: **33/33 checks**, **14 auditorías axe sin violaciones automáticas** y
**27 capturas**. Revisadas capturas a 1440×900 y 1280×800, incluida la tabla de 005/t0 y el fondo del atlas.
Ruff, formato y pyright correctos; **425 tests rápidos pasaron, 5 slow excluidos**; frontend build correcto.
Informe completo y límites: [`QA_UX_UI.md`](QA_UX_UI.md).

**Estado durable:** implementación, fixes, runner y documentación en **`main`**; rama de origen
`feature/ux-ui` conservada. CP-025 (`fad8562`)
recuperó el trabajo de Claude; `af22c29` corrigió lectura/teclado/contraste; CP-026 (`d406354`) respaldó el QA,
el fondo del atlas y las tablas. CP-027 registra el QA final; CP-028 registra la integración. El árbol de
`bcef409` es idéntico al de `06ba62a`, que pasó los checks. No hay implementación pendiente de
F9/F10 ni trabajo necesario que dependa de notas temporales o de la memoria de los agentes.

**Límites:** 12 auditorías conservan resultados incompletos de axe; no se certifica WCAG completa ni se hizo
prueba con lector de pantalla. Sin línea base de capturas, la regresión visual automática es inconclusa.
Los jobs del QA son simulados y no ejecutan ANTs/MONAI ni subidas reales. Capturas/reportes locales se
regeneran con [`tools/e2e/README.md`](../tools/e2e/README.md); verificar siempre su fecha.

### Cómo retomar con Claude u otra herramienta

1. `git checkout main && git pull --ff-only`.
2. Leer este archivo, `PROGRESS.md`, `QA_UX_UI.md` y `PLAN_MVP.md` §14. **No volver a implementar F9/F10.**
3. Si hay cambios nuevos, correr los checks obligatorios y el QA. Para el QA hacen falta los datos y
   resultados de 001/t0 y 005/t0; los modelos/registros no forman parte de esa prueba.
4. El PR #1 ya está fusionado y el tablero actualizado. No repetir el merge; continuar únicamente con el
   siguiente trabajo acordado con el usuario.
5. Las propuestas de la sección 4 siguen sin aprobarse; no empezarlas como continuación automática de §14.

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
- **Fondo de atlas en Niivue:** el shader fuerza la coordenada del LUT a `2/256`; con mínimo 0 puede mezclar
  la etiqueta 1 con el fondo. Conservar las guardas transparentes -2/-1/0 y los nombres indexados por valor real.
- Ejecutar un solo Chrome/SwiftShader de QA a la vez: instancias simultáneas pueden saturar la GPU y caer.
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

## 6. En curso (CP-029): D2 · Docker Compose
Borrador de Codex en la rama **`wip/d2-docker`** (sin probar). Spec y tickets en `PLAN_MVP.md` §15. Para retomar:
`git checkout -b feat/D2-docker-compose origin/wip/d2-docker`, luego `docker compose up -d --build`,
`docker compose ps` (todo *healthy*) y `cd tools/e2e && CERBERUS_UI=http://localhost:8080 node verify-docker.mjs`.
Ojo: el backend es amd64 (Rosetta) por ANTs; el primer build tarda.

**Actualización CP-030:** D2a está hecho en la rama **`feat/D2-docker-compose`** (pusheada); D2b (nginx + smoke) sigue en curso.
Retoma desde esa rama, no desde `wip/d2-docker`.
