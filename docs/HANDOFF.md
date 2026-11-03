# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-11-03 · último checkpoint: CP-037 · rama base: `main`

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

**Implementación integrada en `main`:** MVP completo (B0–B8, F0–F6, D1, E2E), áreas de Brodmann
(§13: B9–B11, F7, F8), dominios funcionales y UX/UI (§14: B12, F9–F11), Docker Compose (§15: D2a–D2c)
y autoajuste de recursos y caché HTTP de NIfTI (§16: D2e-back/front).

| Bloque | Estado | Resultado |
|---|---|---|
| §13–§14 · áreas y UX/UI | ✅ integrado | Capas, cursor, atajos, pestañas, funciones en riesgo, IBM Plex y navegación con teclado; PR #1, merge `bcef409` |
| §15 · Docker Compose | ✅ integrado | Redis, API, worker y frontend/nginx; acceso local en `http://localhost:8080`; CP-031 |
| §16 · recursos y caché | ✅ integrado | `CERBERUS_CPU_THREADS=auto`, `GET /api/system`, indicador y estimaciones en la UI, revalidación 304; CP-034 |
| QA de seguridad y robustez | ⬜ correcciones pendientes | Hallazgos y propuesta por olas en [`QA_2026-10-29.md`](QA_2026-10-29.md); CP-035/036 |

**Trabajo documental (CP-037):** actualización de README, este handoff y navegación del plan en
`docs/D1-refresh-documentation`; integración a `main` pendiente. No modifica la implementación ni corrige
los fallos del QA. No hay trabajo de implementación a medias declarado.

**Validación de CP-037 (2026-11-03):** Ruff, formato y pyright correctos; **474 tests rápidos pasaron,
5 slow excluidos**; frontend build correcto. Comprobados 34 enlaces locales sin errores. No se repitió
QA visual ni Docker en esta actualización documental; los resultados de esas suites que siguen son históricos.

**Siguiente paso:** revisar e integrar la actualización documental. Después, acordar el inicio de la ola P
del QA: P1–P3, P5, S1–S3 y Q1–Q4. La solicitud actual autoriza documentación y publicación en Git;
no incluye implementar esas correcciones.

**QA histórico de UX/UI (CP-027):** `CERBERUS_UI=http://localhost:5180 npm run verify` terminó con exit 0 el
2026-10-29 a las 17:43:15 UTC: **33/33 checks**, **14 auditorías axe sin violaciones automáticas** y
**27 capturas**. Revisadas capturas a 1440×900 y 1280×800, incluida la tabla de 005/t0 y el fondo del atlas.
Ruff, formato y pyright correctos; **425 tests rápidos pasaron, 5 slow excluidos**; frontend build correcto.
Informe completo y límites: [`QA_UX_UI.md`](QA_UX_UI.md).

**QA histórico de Docker y §16 (CP-033/034):** CP-033 registra 474 tests rápidos y comprobaciones de recursos
en el host y con límites cgroup. CP-034 registra el smoke Docker 15/15 y revisión de captura del indicador;
GTV, MONAI y Brodmann devolvieron 304 al volver al estudio. T1Gd de 75 MB devolvió 200 en Chrome headless,
aunque su petición condicional con curl devolvió 304. No se garantiza que el navegador conserve todos los
volúmenes grandes en su caché. Evidencia y mediciones completas en [`PROGRESS.md`](PROGRESS.md).

**Seguridad y datos:** el QA posterior encontró P1 (metadatos personales en la conversión DICOM), Q1/S3
(subidas que agotan la memoria), CSRF y DNS rebinding, entre otros fallos. Siguen sin corregirse. No se debe
presentar la ingesta como anonimización completa ni la limpieza temporal como garantizada ante un crash.

**Límites:** 12 auditorías conservan resultados incompletos de axe; no se certifica WCAG completa ni se hizo
prueba con lector de pantalla. Sin línea base de capturas, la regresión visual automática es inconclusa.
Los jobs del QA de UX/UI son simulados y no ejecutan ANTs/MONAI ni subidas reales. Capturas/reportes locales se
regeneran con [`tools/e2e/README.md`](../tools/e2e/README.md); verificar siempre su fecha.

### Cómo retomar con Claude u otra herramienta

1. `git checkout main && git pull --ff-only`; comprobar si la rama documental de CP-037 ya se integró.
2. Leer este archivo, `PROGRESS.md`, `QA_2026-10-29.md` y `PLAN_MVP.md` §13–§16.
   **No volver a implementar UX/UI, Docker, autoajuste ni 304.**
3. Para desarrollo, usar el arranque de la sección 1. Para Docker: `docker compose up -d --build`,
   `docker compose ps` y abrir `http://localhost:8080`. Backend amd64; en Apple Silicon usa Rosetta.
4. Para cambios de código, correr checks y QA según [`tools/e2e/README.md`](../tools/e2e/README.md).
   UX/UI requiere datos y resultados de 001/t0 y 005/t0; el smoke Docker solo exige la muestra 001/t0.
5. Las correcciones del QA y las propuestas de la sección 4 requieren acordar su alcance con el usuario;
   no empezarlas como continuación automática del trabajo documental.

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

## 4. Mejoras posteriores (propuestas, sin aprobar)
Reporte exportable por estudio (PDF o imprimible), 3D más limpio (iluminación y orientación), subir archivos
arrastrándolos, atajos extra. Fase 2 pendiente: auth, skull-strip (HD-BET o SynthStrip) para DICOM sin
`brain_mask`, registro entre series y RTSTRUCT. Docker y el autoajuste ya están implementados.
El plan de correcciones del QA está en [`QA_2026-10-29.md` §6](QA_2026-10-29.md#6-plan-de-corrección-propuesto-por-olas).

## 5. Protocolo de handoff (para quien trabaje, humano o IA)
- En **cada** checkpoint actualiza la sección 2 de este archivo (estado, trabajo en curso, siguiente paso) en el mismo
  commit que `PROGRESS.md`.
- Si vas a dejar trabajo a medias, súbelo a `wip/<tema>` (aunque no compile) y anótalo aquí.
- Nunca dejes en tu máquina, sin subir, lo único que alguien necesita para continuar.

## 6. Referencias históricas

La evolución de Docker y recursos está en CP-029–CP-034 de [`PROGRESS.md`](PROGRESS.md);
los hallazgos del QA, en CP-035/036. Las ramas `wip/d2-docker`, `feat/D2-docker-compose` y
`feat/D2e-autotune` describen etapas anteriores, no trabajo que haya que retomar. La decisión vigente es
`CERBERUS_CPU_THREADS=auto` y caché en el navegador con ETag/304, sin `proxy_cache` en nginx.
