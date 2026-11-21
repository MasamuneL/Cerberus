# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-11-21 · último checkpoint: CP-084 · rama base: `main`

## 1. Arranque rápido

```bash
git checkout main && git pull --ff-only && git lfs pull
uv sync && (cd frontend && npm install)
redis-server                                                    # terminal 1
uv run python -m cerberus_api.worker                   # terminal 2
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

Última integración relevante: **CP-084** (ronda §26 en cierre; historial completo en [`PROGRESS.md`](PROGRESS.md)).

### Qué funciona
- **App web (MVP + §13–§24):** visor 2D/3D Niivue (capas, bordes suaves, fallback `ViewerErrorBoundary` y botón «Reintentar» `UI1`), volumetría/RANO longitudinal, segmentación MONAI (`EVAL1`: Dice TC vs GTV 0.824 ± 0.159 en n=8, 0.888 ± 0.026 con 4 canales en n=6; [`EVAL_MONAI.md`](EVAL_MONAI.md)), subida NIfTI/DICOM y auth OIDC/Keycloak A0–A4 (`demo`/`demo`).
- **Áreas de Brodmann (`ATLAS1` + `REG1`):** proyección Talairach→MNI152 con `icbm_other2tal` de Lancaster (`storage/` local de 7 estudios remapeado; reportes viejos avisan para remapear). Registro afín en subproceso de 1 hilo + semilla 42 y `SyNOnly` multihilo; caché v2.
- **Operación y soporte:** lanzador [`up.sh`](../tools/launch/up.sh) / `up.ps1`, modo híbrido macOS (`HW4`), perfiles `full`/`fast` (`HW3`), imagen CUDA (`HW1`), autoajuste de recursos y caché 304, y diagnóstico 502 (`D3R`: `cerberus_api.diagnostics`).

### Qué no es válido todavía
- **Fine-tuning (`cerberus_training`):** `FT0`–`FT5` probados solo con `smoke --synthetic`; nunca ejecutado en real (1/8 estudios locales elegibles; dataset TCIA de 208 GB no cabe hoy). Ver [`TRAINING.md`](TRAINING.md).
- **Áreas de Brodmann:** estimación educativa sobre atlas de un único cerebro; `icbm_other2tal` no está validada para la plantilla ICBM152 2009a sym ([`ATLAS_ESPACIOS.md`](ATLAS_ESPACIOS.md)).
- **Reproducibilidad `REG1`:** 3/3 hashes idénticos comprobados solo en `004/t0` (`full` y `fast`); falta comprobar otros estudios y Linux/Docker amd64.
- **Plataformas sin validar:** perfil CUDA en PC NVIDIA (`compose.gpu.yaml`) y `tools/launch/up.ps1` en Windows siguen pendientes.
- **E2E sensibles a la carga:** SwiftShader bloquea/expira con carga alta; correr uno a uno en reposo (`verify` 33/33 y `chunk-error` 5/5 pasaron en `UI1`, aunque un revisor con carga 10–22 falló).
- **Seguridad/datos ([`QA_2026-10-29.md`](QA_2026-10-29.md)):** ola P pendiente salvo `S1`/`S2` (cerrados en `A3`); `A5` (E2E de auth) depende de la ola P.

### Pendientes priorizados
1. **Demo:** §26 cerrada (CP-084; e2e de main en verde). Ensayar la demo en la máquina del profesor con [`README.md`](../README.md) y usar `D3R` (`python -m cerberus_api.diagnostics --compose-stdin` en `api`) si vuelve el 502.
2. **Documentación y PRs:** actualizar [`PLAN_MVP.md` §13](PLAN_MVP.md#13-fase-2--áreas-de-brodmann-y-funciones-afectadas) (aún describe el atlas como MNI); decidir cierre del [PR #17](https://github.com/MasamuneL/Cerberus/pull/17) (rescatado en `D3R` / PR #40).
3. **Registro (`REG1`):** QC automático del afín (determinante/rotación/Dice en `warnings`, fuera de §26) y pruebas en más estudios / Docker amd64.
4. **Visor (`CP-070`):** perfilar el ~92 % del toggle de capas (refrescos GL en `Viewer.tsx`) antes de otro ticket de rendimiento.
5. **Hardware y seguridad:** validar NVIDIA y `up.ps1` en Windows; acordar ola P + `A5`; piloto/entrenamiento real según [`TRAINING.md`](TRAINING.md).

### Cómo arrancar
- **Recomendado (Docker + hardware):** `tools/launch/up.sh --dry-run` y `tools/launch/up.sh` (Windows: `tools\launch\up.ps1`). Detalles en [`README.md`](../README.md) y reglas en [`AGENTS.md`](../AGENTS.md).
- **Desarrollo nativo (4 terminales) y checks:** ver `§1. Arranque rápido` arriba.
- **No reabrir lo cerrado:** UX/UI, Docker, autoajuste y caché 304 ya están hechos. Las correcciones del QA y las propuestas de §4 requieren acordar alcance con el usuario; no empezarlas como continuación automática.

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
Adaptación de MONAI a CFB-GBM: discusión conservada en
[`NOTA_FINETUNING_MONAI.md`](NOTA_FINETUNING_MONAI.md) para generar después el plan con Astra.
No se ha aprobado ni iniciado entrenamiento; falta decidir GTV binario frente a etiquetas TC/WT/ET.

Reporte exportable por estudio (PDF o imprimible), subir archivos
arrastrándolos, atajos extra. Fase 2 pendiente: skull-strip (HD-BET o SynthStrip) para DICOM sin
`brain_mask`, registro entre series y RTSTRUCT. Docker y el autoajuste ya están implementados.
El login para la demo tiene planificación incorporada en `PLAN_MVP.md` §17; A0–A3 integrados, con A4/A5
pendientes. La evolución hospitalaria se describe aparte y no se considera aprobada para ejecución.
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
