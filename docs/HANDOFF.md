# HANDOFF — retomar el trabajo con cualquier IA (Codex, Claude Code, …)

> Este archivo describe **el estado vivo**: qué está a medias ahora mismo y cómo continuar. Se actualiza en cada
> checkpoint. El historial completo está en [`PROGRESS.md`](PROGRESS.md) y el alcance y los contratos en
> [`PLAN_MVP.md`](PLAN_MVP.md). Las reglas de trabajo están en [`../AGENTS.md`](../AGENTS.md).

**Última actualización:** 2026-11-10 · último checkpoint: CP-046 · rama base: `main`

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

**Docker local · 2026-11-10:** imágenes en ejecución construidas desde
`/private/tmp/cerberus-a4-metrics-docker-20261110`: snapshot completo de `feat/A4-auth-ui`
(`52ebb0b`) más código B13 (`2c48e71`, adaptando SegmentationPanel al control de sesión de A4).
Esta construcción sustituye la mezcla anterior de main y archivos sueltos. A4 conserva tanto
la pantalla de login como `prompt=login`: reconstruir solo desde main o B13 elimina esos cambios.
Compose y `.env.auth` de ejecución siguen en `/private/tmp/cerberus-auth-A1`.
Tests sobre el snapshot combinado con su entorno: **766 rápidos aprobados, 5 slow excluidos**.
QA real en Chrome con cuenta temporal eliminada al terminar: logout devuelve API a 401;
la siguiente entrada exige contraseña vacía con «Recordarme» activado y desactivado;
la cookie persistente KEYCLOAK_REMEMBER_ME solo aparece con la opción activada.
Durante la recreación de API hubo un 504 al consultar un job; arq recuperó la segmentación
001/t0 en el segundo intento y completó el 2026-11-10 a las 15:43:44 UTC, con métricas nuevas.
TC/GTV: Dice 0.856827, recall 0.829519, precisión 0.885993, HD95 3.741657 mm.
Los resultados están en storage/results/001/t0/monai_seg.json; no requieren nueva inferencia.

**CP-046 · 2026-11-10:** integrado el [PR #11](https://github.com/MasamuneL/Cerberus/pull/11),
merge `d68262a`. Main contiene A4 completa, métricas B13, limpieza CP-043 y nota de fine-tuning
para Astra. README documenta `demo` / `demo`, verificado en Docker; el bootstrap no crea la cuenta.
La construcción desde main ya incluye login, `prompt=login` y métricas: no necesita combinar snapshots.
Checks del árbol integrado: 766 tests rápidos, Ruff, formato, pyright y build correctos;
15 pruebas Node y 20 escenarios de UI de autenticación aprobados. QA visual final: 33/33 checks,
14 auditorías axe sin violaciones automáticas y 27 capturas; revisadas Segmentación en ambos tamaños.
Siguiente paso: ola P y A5 según el plan; no iniciar fine-tuning sin el plan posterior con Astra.

**Implementación integrada en `main`:** MVP completo (B0–B8, F0–F6, D1, E2E), áreas de Brodmann
(§13: B9–B11, F7, F8), dominios funcionales y UX/UI (§14: B12, F9–F11), Docker Compose (§15: D2a–D2c)
y autoajuste de recursos y caché HTTP de NIfTI (§16: D2e-back/front).

| Bloque | Estado | Resultado |
|---|---|---|
| §13–§14 · áreas y UX/UI | ✅ integrado | Capas, cursor, atajos, pestañas, funciones en riesgo, IBM Plex y navegación con teclado; PR #1, merge `bcef409` |
| §15 · Docker Compose | ✅ integrado | Redis, API, worker y frontend/nginx; acceso local en `http://localhost:8080`; CP-031 |
| §16 · recursos y caché | ✅ integrado | `CERBERUS_CPU_THREADS=auto`, `GET /api/system`, indicador y estimaciones en la UI, revalidación 304; CP-034 |
| §17 · login para demo académica | 🟡 A0–A4 integrados | PR #11, merge `d68262a`; login, permisos, continuidad y reautenticación. A5 pendiente |
| §18 · métricas y guía | ✅ integrado | PR #11; TC/WT frente a GTV, casos vacíos y JSON antiguos compatibles |
| QA de seguridad y robustez | ⬜ correcciones pendientes | Hallazgos y propuesta por olas en [`QA_2026-10-29.md`](QA_2026-10-29.md); CP-035/036 |

**Integración:** CP-037, CP-038 y CP-039 integrados en `main` mediante los PR #2, #3 y #4
(merges `42d39db`, `f45e5e7` y `c2e0a4c`). El plan funcional integrado llega hasta §16;
A0 está integrado mediante el [PR #5](https://github.com/MasamuneL/Cerberus/pull/5), merge `3bd8ee4`.
A1 está integrado mediante el [PR #6](https://github.com/MasamuneL/Cerberus/pull/6), merge `5470dcf`.
A2 está integrado mediante el [PR #8](https://github.com/MasamuneL/Cerberus/pull/8), merge `7635e58`, tras QA real
y smoke Docker completos (CP-044). La limpieza/CP-043 está incorporada mediante el PR #11 (CP-046).

**Validación de CP-037 (2026-11-03):** Ruff, formato y pyright correctos; **474 tests rápidos pasaron,
5 slow excluidos**; frontend build correcto. Comprobados 34 enlaces locales sin errores. No se repitió
QA visual ni Docker en esta actualización documental; los resultados de esas suites que siguen son históricos.

**Validación de CP-039 (2026-11-03):** checks obligatorios correctos, **474 tests rápidos aprobados,
5 slow excluidos** y 35 enlaces locales comprobados. Contratos vigentes de §6/§7 intactos y A0–A5 pendientes.
Solo cambian documentos; el login y su E2E no se han implementado ni ejecutado.

**CP-040 · A0 (2026-11-05):** el usuario autorizó continuar con el inicio de sesión. En `feat/A0-auth-config`,
Codex implementó `Settings` para `off`/`oidc`, URLs públicas/backchannel, secreto protegido, cookies y timeouts;
`Principal` inmutable y contratos `AuthConfig`/`AuthSession` en Python/TypeScript. Los tests aíslan el entorno
OIDC antes de importar la app y lo restauran al salir de pytest. **568 tests rápidos aprobados, 5 slow
excluidos**, Ruff/formato/pyright y build correctos; paridad de tipos comprobada compilando contratos
generados del JSON Schema contra las interfaces reales. Revisión independiente: un hallazgo de aislamiento
ambiental, corregido y verificado con regresión que fallaba antes del cambio. Plan de ejecución en
[`superpowers/plans/2026-11-05-A0-auth-config.md`](superpowers/plans/2026-11-05-A0-auth-config.md).
No incluye rutas OIDC, Keycloak ni UI; configurar `oidc` todavía no protege los recursos. A1–A5 siguen pendientes;
**A1 integrado (CP-042):** `feat/A1-keycloak`, merge `5470dcf`; worktree de desarrollo `/private/tmp/cerberus-auth-A1`.
Overlay con Keycloak 26.8.1 y PostgreSQL 18, imágenes por digest; bootstrap crea `.env.auth` con permisos
0600 y conserva archivos existentes. Realm sin usuarios, cliente confidencial con PKCE S256 y mapper
de roles limitado a `cerberus-web`. **575 tests rápidos aprobados**, Ruff/formato/pyright correctos y build
correcto. QA real del proveedor: issuer/JWKS desde API, callback exacto, rechazo de redirect ajeno, lector y
analista con Authorization Code+PKCE en Chrome, claim correcto y cuentas/contraseñas conservadas tras
reiniciar PostgreSQL/Keycloak; cuentas temporales de QA eliminadas. Captura del login en español revisada.
Revisión independiente sin hallazgos. Smoke Docker de la UI completo antes de integrar: **15/15 checks**,
11 capturas, sin pendientes; revisadas 1440×900 y 1280×800 (14:01–14:04 UTC).
Se corrigieron URLs HTTP de Debian a HTTPS en el Dockerfile: el build limpio fallaba con HTTP 403;
las firmas de paquetes siguen verificándose. No incluye rutas/sesiones de Cerberus ni protección todavía.
**A2 integrado:** `feat/A2-oidc-sessions`, merge `7635e58`, worktree `/private/tmp/cerberus-auth-A1`.
Se conserva `.env.auth` local para el QA real; A0–A2 ya están en `main`.
**Avance A2 (2026-11-06):** transacciones ligadas al navegador y de un uso, sesiones opacas con renovación,
timeouts Redis atómicos, cliente OIDC Authlib 1.9.4/HTTPX2/joserfc y rutas config/login/callback/me/logout.
Firma RS256 y claims OIDC verificados; CSRF/Origin en logout. Callbacks excluyen query de logs de Uvicorn y
nginx, incluida la barra final y los fallos de upstream. **649 tests rápidos aprobados, 5 slow excluidos**,
Ruff/formato/pyright y build correctos. Cambios subidos hasta `f93acdd`.
Revisión detectó `azp` vacío/falso: regresiones RED→GREEN y validación explícita por Authlib. QA real también
detectó claim de roles omitido por Keycloak: ahora cuenta sin rol recibe 403. La pasada final real confirmó
login de lector y analista, renovación, CSRF, logout, state ajeno/replay, Redis/proveedor caídos y caducidad,
restaurando configuración y eliminando cuentas temporales. Smoke Docker previo al merge completo:
2026-11-06 21:30:11–21:32:50 UTC, **15/15 checks**, 11 capturas, sin pendientes y exit 0. Revisadas capturas
de recursos a 1440×900 y volumetría a 1280×800. Logs de Uvicorn y nginx verificados con marcadores sintéticos;
los callbacks no registran query incluso con API caída y barra final.
**A3 integrado (CP-045):** PR #9, merge `9674ee4`, rama `feat/A3-access-control`, dentro del mismo worktree `/private/tmp/cerberus-auth-A1`.
Implementados guardas antes del body/I/O, propiedad antes de encolar y limpieza, caché autenticada,
CSRF y Host (S1/S2). Integrado tras QA completo; A4 añadirá UI. **725 tests rápidos aprobados, 5 slow excluidos**,
Ruff/formato/pyright/build correctos. Revisión independiente cerró bypass por `root_path` y propietarios
sin TTL en fallos tempranos de arq; regresiones reales sobre fakeredis y nuevo launcher `python -m cerberus_api.worker`.
QA real lector/dos analistas, acceso cruzado, TTL y GET/HEAD condicional tras logout correcto. Worker Docker
probado con función ausente/reintentos agotados; propiedad caduca. QA final real repitió permisos y la
regresión A2 completa con el launcher nuevo: Redis/proveedor caídos, state/replay, caducidad y logout correctos;
cuentas temporales eliminadas y timeouts restaurados. Visual Vite **33/33**, 14 auditorías axe sin violaciones
automáticas y 27 capturas (22:01:16–22:07:03 UTC); smoke Docker **15/15**, 11 capturas, sin pendientes
(22:08:20–22:11:07 UTC). Revisadas capturas de capas 1440×900 y tabla 005/t0 1280×800, y recursos/volumetría
Docker en ambas resoluciones. La restauración del wrapper de QA falló por cwd; corregida y ejecutada
manualmente: `/auth/config` informa `oidc` y catálogo anónimo devuelve 401. No es un fallo del runner ni del producto.
**A4 integrada en CP-046:** el PR #11 incorpora `52ebb0b` y conserva las correcciones de
sesión, medios, continuidad y proveedor. La validación del conjunto final se describe arriba y en
PROGRESS. Los informes del 2026-11-06 son históricos; A5 y la ola P siguen pendientes.
Plan de ejecución: [`superpowers/plans/2026-11-05-auth-remaining.md`](superpowers/plans/2026-11-05-auth-remaining.md).
El usuario autorizó avanzar los tickets posibles con commits/push frecuentes y QA antes de cada merge.
A5 depende de la ola P del QA
(P1–P3, P5, S1–S3 y Q1–Q4); S1/S2 están cerrados por A3.

**Verificación visual de CP-040:** `CERBERUS_UI=http://localhost:5180 node verify.mjs` se ejecutó contra
API/Vite de esta rama. Completó 10 comprobaciones a 1440×900 y generó 9 capturas nuevas; quedó sin avanzar
después de `1440x900_segmentación.png`, durante la auditoría de ese panel. Se interrumpió la ejecución;
no hay aprobación global ni verificación a 1280×800. Revisadas las capturas de capas y segmentación,
sin defectos visuales observados en ellas. `shots/report.json` registra la ejecución parcial: 10/13 checks,
con errores de navegador cerrado tras SIGINT y exit 130. No se modificó el runner ni se declaró aprobación
completa de QA; las capturas restantes con fecha anterior siguen siendo históricas.

**QA previo a integración de A0 (2026-11-05):** nueva ejecución completa sin modificar el runner,
13:43–13:48 UTC: **33/33 checks**, **14 auditorías axe sin violaciones automáticas**, 27 capturas y exit 0.
Revisadas las capturas nuevas de capas a 1440×900 y tabla 005/t0 a 1280×800. El bloqueo anterior no se reprodujo;
esta evidencia reemplaza la ejecución parcial como validación actual de A0. Ruff/formato/pyright y **568 tests
rápidos** correctos; build de frontend correcto. No prueba autenticación real, todavía pendiente de A1–A5.

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
(subidas que agotan la memoria), entre otros fallos. S1/S2 (CSRF/DNS rebinding) están corregidos por A3; el resto sigue pendiente. No se debe
presentar la ingesta como anonimización completa ni la limpieza temporal como garantizada ante un crash.

**Límites:** 12 auditorías conservan resultados incompletos de axe; no se certifica WCAG completa ni se hizo
prueba con lector de pantalla. Sin línea base de capturas, la regresión visual automática es inconclusa.
Los jobs del QA de UX/UI son simulados y no ejecutan ANTs/MONAI ni subidas reales. Capturas/reportes locales se
regeneran con [`tools/e2e/README.md`](../tools/e2e/README.md); verificar siempre su fecha.

### Cómo retomar con Claude u otra herramienta

1. `git checkout main && git pull --ff-only`; A0–A3 integrados. Continuar A4 según el tablero.
2. Leer este archivo, `PROGRESS.md`, `QA_2026-10-29.md` y `PLAN_MVP.md` §13–§17.
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
Adaptación de MONAI a CFB-GBM: discusión conservada en
[`NOTA_FINETUNING_MONAI.md`](NOTA_FINETUNING_MONAI.md) para generar después el plan con Astra.
No se ha aprobado ni iniciado entrenamiento; falta decidir GTV binario frente a etiquetas TC/WT/ET.

Reporte exportable por estudio (PDF o imprimible), 3D más limpio (iluminación y orientación), subir archivos
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
