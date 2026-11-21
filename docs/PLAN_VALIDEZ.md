# PLAN_VALIDEZ — ronda de validez científica y demo (§26)

Plan para ejecutar en una sesión nueva de Claude Code como **orquestador** (Opus) dentro de Herdr, con subagentes
Claude, Codex y Antigravity. Escrito el 2026-11-21 tras CP-074.

## 0. Por qué esta ronda

El código está sano (1237 tests, contratos fijos, revisión por PR), pero los resultados que se enseñan no están
validados:

1. **Brodmann:** el atlas de nilearn declara espacio **Talairach** y el registro usa **MNI152**, sin conversión
   (hallazgo de CP-047, sin resolver). La función «áreas afectadas» tiene la base más débil.
2. **Registro no determinista:** el registro ANTs `full` da resultados distintos entre corridas con varios hilos (REG1, §25).
3. **MONAI sin evaluación:** un único Dice (0.857 en 001/t0). Falta la tabla de todos los estudios.
4. **Fine-tuning:** el pipeline FT0–FT5 existe, pero nunca se ejecutó. El usuario puede descargar más datos de
   CFB-GBM, pero no tiene dónde guardarlos. Se documenta como **pasos futuros**, sin entrenar.
5. **Demo:** el 502 del profesor no tiene diagnóstico. El PR #17 (D3) trae `diagnostics.py`, pero lleva 9 días
   parado y en conflicto con main.

**Congelado en esta ronda:** no se abren tickets nuevos de rendimiento ni de infraestructura (Docker, Keycloak, CUDA,
lanzadores). Lo que encuentres va a «Pendientes» del handoff.

## 1. Rutas y constantes

| Nombre | Valor |
|---|---|
| `REPO` | `/Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus` |
| `WT` | `/Users/vikingo/Documents/UDG2/5toSem/BigData/Cerberus-wt/<ID>` |
| `PYPATH` | `/Users/vikingo/.pyenv/versions/3.11.9/bin` (`uv` solo existe vía este shim) |
| `SP` | scratchpad de la sesión nueva (lo da el entorno). Prompts en `SP/prompts/`, informes en `SP/reports/` |
| `ORQ` | `echo $HC_TERMINAL_ID` de la sesión nueva |
| Datos reales | `REPO/Data` (ruta absoluta; los worktrees no tienen `Data/` completo) |

## 2. Agentes: quién hace qué

### 2.1 Comandos de lanzamiento (firmas verificadas el 2026-11-21)

Todos se lanzan como terminales Herdr para que se vean en la barra lateral. El prompt largo va en un archivo
`SP/prompts/<name>.md`.

**Claude** (igual que en las rondas PERF/§24):
```sh
hc run --bg --name <name> --cwd <WT> -- env PATH="PYPATH:$PATH" \
  claude --model <sonnet|opus> --permission-mode auto "Lee y ejecuta exactamente SP/prompts/<name>.md" --add-dir=SP
```
El prompt va **antes** de `--add-dir=` porque esa opción es variádica.

**Codex** (`codex-cli 0.171.0`, modelo por defecto en `~/.codex/config.toml`: `gpt-6-astra`):
```sh
hc run --bg --name <name> --cwd <WT> -- env PATH="PYPATH:$PATH" \
  codex exec -C <WT> -s workspace-write \
    -c sandbox_workspace_write.network_access=true \
    --add-dir SP --add-dir "$(env PATH=PYPATH:$PATH uv cache dir)" \
    -o SP/reports/<name>.last.md \
    "Lee y ejecuta exactamente SP/prompts/<name>.md"
```
Para los revisores Codex: `-s read-only` en vez de `workspace-write` (y sin `network_access`).

**Antigravity** (`agy 1.5.14`; flags estilo Go: **todas las opciones antes de `-p`**, y `-p "<prompt>"` al final):
```sh
hc run --bg --name <name> --cwd <WT> -- env PATH="PYPATH:$PATH" \
  agy --model <AGY_MODEL> --mode auto --add-dir SP --print-timeout 0 -p "Lee y ejecuta exactamente SP/prompts/<name>.md"
```
`AGY_MODEL` sale de la calibración (§3, paso 5). Para revisores: `--mode plan` (solo lectura).

### 2.2 Reglas de git según el agente (sin excepciones)

- **Hijos Claude:** hacen commit, push y `gh pr create` ellos mismos y reportan con `hc send ORQ "..."`, como antes.
- **Hijos Codex y Antigravity: NO ejecutan `git commit`, `git push` ni `gh`.** Dejan los cambios sin commitear en su
  worktree y escriben dos archivos: `SP/reports/<name>.md` (informe) y `SP/reports/<name>.pr.md` (cuerpo del PR en
  español). Terminan su proceso al acabar; el orquestador detecta el fin con `hc wait --children any`.
- Cuando acaba un hijo Codex o Antigravity, el orquestador:
  1. Comprueba con `git -C <WT> status --short` que solo cambiaron los archivos permitidos. Si hay otros, revierte esos
     archivos con `git -C <WT> checkout -- <archivo>` y lo anota.
  2. Hace commit con el mensaje convencional del ticket. En el cuerpo pone `Implementado por <Codex gpt-6-astra | Antigravity AGY_MODEL>`
     y termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  3. `git push -u origin <rama>` y `gh pr create --base main --title "<ID>: ..." --body-file SP/reports/<name>.pr.md`.
     El cuerpo termina con `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Revisor de otra familia que el implementador**, siempre, para no repetir los mismos sesgos. El revisor no edita nada.
  La primera línea de su informe es `APROBADO` o `CAMBIOS`.
- **Ronda de cambios con un implementador Codex/Antigravity:** se lanza otra vez con el mismo nombre y el prompt
  `SP/prompts/<name>-r2.md`, que lista los hallazgos. Nunca se reanuda la sesión anterior. Máximo 2 rondas; después se consulta al usuario.

### 2.3 Asignación (cada fila dice por qué ese agente)

| Ticket | Implementa | Revisa | Por qué |
|---|---|---|---|
| ATLAS0 · informe atlas/espacios | Antigravity | Claude opus | Investigación con lectura larga (fuentes de nilearn y docs) y mediciones; la validez científica la revisa opus |
| REG1 · registro determinista | Codex | Antigravity | Numérico y backend con tests; la revisión es mecánica (repetir corridas y comparar hashes) |
| EVAL1 · evaluación MONAI | Codex | Claude opus | Script con modelo real; las métricas y su interpretación requieren criterio científico |
| D3R · rescate del diagnóstico de #17 | Codex | Antigravity | Port de código Python acotado; la revisión es de diff y privacidad |
| FT-DOC · pasos futuros del fine-tuning | Antigravity | Codex | Documentación larga; Codex/Astra hizo el plan de fine-tuning y conoce el pipeline |
| ATLAS1 · aplicar la opción elegida | Codex | Claude opus | Cambio de código con impacto científico |
| UI1 · botón «Reintentar» | Antigravity | Claude sonnet | Pequeño, visual (lee PNG); revisión barata |
| DOC1 · compactar el HANDOFF | Antigravity | Claude sonnet | Mucho contexto (HANDOFF + PROGRESS enteros) |

## 3. Fase 0 · arranque (lo hace el orquestador en main)

1. `cd REPO && git checkout main && git pull --ff-only`. Lee `AGENTS.md`, `docs/HANDOFF.md` §2, el final de
   `docs/PROGRESS.md` y `docs/PLAN_MVP.md` §5–§7, §12, §24 y §25.
2. **Otra sesión:** `hc ls`. Si hay otro `claude-code` con cwd en `REPO` (en la ronda anterior, t32 llevaba el §25 HW),
   **no toques** archivos de §25 (`tools/launch/`, `compose*.yaml`, `docker/`) y pregunta al usuario con
   AskUserQuestion quién lleva REG1. Si no hay otra sesión y REG1 sigue ⬜ sin rama (`git ls-remote --heads origin 'feat/REG1*'` vacío), REG1 es tuyo.
3. **Commit del plan:** `docs/PLAN_VALIDEZ.md` está sin commitear. Añade a `docs/PLAN_MVP.md` una sección
   `## 26. Validez científica y demo` con la tabla de tickets de §5 de este archivo y un enlace a `PLAN_VALIDEZ.md`, y
   filas en el tablero de `PROGRESS.md` (🟡 la oleada 1, ⬜ el resto). Commit `chore(progress): plan §26 validez científica` y push.
4. **e2e de main pendiente de la ronda anterior:** espera a que `uptime` dé una media de carga de 1 minuto < 8
   (compruébalo cada 5 minutos con Monitor; no hagas polling con sleep). Si tras 30 minutos sigue alta, pregunta al
   usuario. Después levanta el stack desde `REPO` (`stack-redis`, `stack-worker`, `stack-api` en :8000) y un Vite
   `final-vite` en :5180. Corre UNO A UNO desde `tools/e2e` con `CERBERUS_UI=http://localhost:5180`:
   `verify.mjs` (33), `verify-viewer-3d.mjs` (7), `verify-mask-surface.mjs` (3), `verify-overlay-toggle.mjs` (4),
   `verify-viewer-chunk-error.mjs` (5). Lee los `report.json` (campos `checks` y `errors`), no cuentes líneas. Revisa las PNG con Read.
   Si algo falla de forma reproducible con la carga baja, es una regresión: para y avisa al usuario.
5. **Smoke de agentes** (en un worktree desechable `WT=../Cerberus-wt/SMOKE`, creado desde `origin/main`, con
   `uv sync` y `npm install` en `frontend`):
   - Tarea idéntica para todos, en `SP/prompts/smoke.md`: «Escribe en `SP/reports/smoke-<agente>.md`: (1) cuántos
     tickets tiene la tabla de §21 de `docs/PLAN_MVP.md` y sus IDs; (2) la última línea de
     `uv run pytest -q backend/tests/test_catalog.py`; (3) si `cd frontend && npm run build` terminó bien. No edites nada más.»
   - Codex: una corrida. Antigravity: una corrida por modelo con `gemini-4-neon-high`, `gemini-4-argon-high` y
     `gemini-4-hydrogen-high`, **una detrás de otra**.
   - Criterio objetivo para elegir `AGY_MODEL`, en este orden: (a) terminó sin quedarse `blocked`; (b) acierta los 3
     datos (7 tickets PERF1–PERF7; la línea de pytest coincide con la tuya; build correcto); (c) menor tiempo de
     reloj. Si hay empate, gana `gemini-4-neon-high`. Anota el resultado en `SP/reports/calibracion.md`.
   - Si Codex o Antigravity se quedan `blocked` por permisos (`hc get <name>`), **no** añadas
     `--dangerously-bypass-approvals-and-sandbox` ni `--dangerously-skip-permissions` por tu cuenta: pregunta al
     usuario. Si un agente no funciona, sus tickets pasan a Claude sonnet y se anota.
   - Borra el worktree: `git worktree remove ../Cerberus-wt/SMOKE --force` y `git branch -D smoke` (rama `smoke` creada para esto).

## 4. Reglas comunes de los hijos (van en `SP/prompts/common-impl.md` y `common-rev.md`)

Copia de la ronda anterior, con estos cambios:
- El orquestador es `ORQ`. Solo los hijos Claude usan `hc send ORQ "<name>: listo|APROBADO|CAMBIOS|BLOQUEADO · detalle en <ruta>"`.
- Los hijos Codex/Antigravity siguen §2.2: no hay git y, al terminar, salen.
- Sin subagentes ni `hc run`, salvo su propio Vite en el puerto asignado, que cierran al terminar.
- No tocan `main`, `PROGRESS.md`, `HANDOFF.md` ni `PLAN_MVP.md` (salvo la excepción explícita del ticket).
- Solo editan los archivos de su ticket. Scripts temporales y mediciones: en `SP/bench/`, nunca en el repo.
- Cumplen `AGENTS.md` sin excepciones: privacidad DICOM, `load_nifti`, validación de rutas, idioma, terminología
  **GTV** (nunca «tumor» en la UI) y citar el rango portado del notebook.
- Los e2e se corren UNO A UNO. Puertos de Vite asignados por ticket (§5). Nunca se commitea `tools/e2e/shots/`.
- **Honestidad:** si una medición sale mal o no concluye, se escribe tal cual. Nada de «mejoras» sin número.

## 5. Tickets

### Oleada 1 (en paralelo; ningún archivo compartido)

**ATLAS0 · informe de espacios del atlas** · rama `feat/ATLAS0-atlas-spaces` · Vite: no
- Archivos: nuevo `docs/ATLAS_ESPACIOS.md`. Nada más.
- Contenido obligatorio:
  1. Qué atlas se carga exactamente: función, versión y espacio declarado. Verifícalo en el código instalado
     (`.venv/lib/python3.11/site-packages/nilearn/datasets/atlas.py`, función que use `backend/cerberus_api/atlas.py`)
     y cita archivo:línea.
  2. A qué plantilla registra el backend (archivo:línea en `atlas.py` o donde la encuentres con `grep -rn "MNI\|mni" backend/cerberus_api`).
  3. **Medición:** aplica al mapa de etiquetas la transformación de Lancaster (icbm2tal o tal2icbm; cita el paper y la
     matriz). Para los 8 estudios de `REPO/Data`, compara las áreas reportadas con y sin la corrección: áreas
     solapadas y a ≤ `MARGIN_MM` (constante de `areas.py`), con tabla por estudio de áreas que aparecen o desaparecen y
     desplazamiento medio de los centroides de las BA en mm. Usa los registros ya calculados en `storage/` si existen;
     si no, ejecuta el mapeo (es lento: uno a uno).
  4. Tres opciones con pros, contras, coste y licencia:
     A) aplicar la transformación de Lancaster;
     B) usar un atlas de Brodmann nativo en MNI (busca candidatos y su licencia; no descargues nada al repo);
     C) mantener el actual y etiquetar «aproximado» en la UI, el README y los reportes.
  5. Una recomendación justificada con los números del punto 3.
- Criterio: tabla del punto 3 con los 8 estudios (o los que se pudieron, con el motivo de los que faltan), y cada
  afirmación técnica con su fuente (archivo:línea o referencia bibliográfica).
- **Gate:** tras el APROBADO del revisor, merge, y el orquestador pregunta al usuario con AskUserQuestion: A, B o C
  (marcando como «Recommended» la recomendación del informe). ATLAS1 no arranca sin esa respuesta.

**REG1 · registro determinista** · rama `feat/REG1-reproducible-registration` · Vite: no · *solo si §3 paso 2 lo asigna a esta sesión*
- Localiza el módulo: `grep -rn "CERBERUS_REGISTRATION\|ants.registration" backend/cerberus_api`.
- Archivos: ese módulo, su archivo de tests y, si hace falta, `backend/cerberus_api/config.py`. Nada más.
- Cambio: fija la semilla y el número de hilos de ANTs. Verifica en
  `.venv/lib/python3.11/site-packages/ants/registration/` qué parámetros acepta `ants.registration` (por ejemplo
  `random_seed`) y qué variable de entorno controla los hilos de ITK (`ITK_GLOBAL_DEFAULT_NUMBER_OF_THREADS`).
  Cita archivo:línea. No inventes parámetros.
- Medición con datos reales, 004/t0 (el estudio donde se vio el problema): 3 corridas `full` → hash SHA-256 del mapa
  de etiquetas registrado idéntico en las 3. Lo mismo con `fast`. Tiempo por corrida antes y después: si fijar hilos lo
  hace más lento, dilo con el número.
- Tests: un test (marcado `slow` si usa ANTs real) que compruebe que dos corridas dan arrays idénticos, y un test
  rápido de que la semilla y los hilos se pasan (con mock).
- Criterio: hashes idénticos en 3/3 para `full` y `fast`; tiempos honestos; sin cambio de §6/§7.

**EVAL1 · evaluación de MONAI en todos los estudios** · rama `feat/EVAL1-monai-evaluation` · Vite: no
- Archivos: nuevo `tools/eval/monai_all.py`, nuevo `docs/EVAL_MONAI.md`. Nada más.
- Reutiliza las funciones existentes. Encuéntralas con `grep -rn "def dice\|hd95\|def segment" backend/cerberus_api`:
  la segmentación del worker y las métricas de B13. **No reimplementes métricas.**
- Ejecuta la segmentación real para cada estudio de `REPO/Data` que tenga GTV y las secuencias necesarias, uno a uno.
  Usa `storage/results` si ya hay un `monai_seg` vigente (comprueba que la fecha es posterior a la de los pesos) y di
  cuáles se reutilizaron.
- `docs/EVAL_MONAI.md`: tabla por estudio (paciente, tiempo, volumen GTV en cm³, volumen TC predicho en cm³, Dice,
  HD95, recall y precisión de TC frente a GTV), media ± desviación estándar y n. Limitaciones: modelo preentrenado en
  BraTS aplicado a CFB-GBM, diferencia de definición TC frente a GTV y n pequeño. Estudios excluidos con su motivo.
  Comando exacto para reproducirla.
- Criterio: el revisor vuelve a ejecutar el script y obtiene la misma tabla (±1e-6).

**D3R · rescate del diagnóstico del PR #17** · rama `feat/D3R-diagnostics` · Vite: no
- Origen: `git fetch origin pull/17/head:pr17` (lo hace el orquestador en el worktree antes de lanzar al hijo).
- Archivos: `backend/cerberus_api/diagnostics.py`, `backend/tests/test_diagnostics.py` (ambos tomados de `pr17`) y
  `README.md` (solo una sección nueva «Diagnóstico de un 502»). Nada más.
- `diagnostics.py` (344 líneas en #17) solo importa `cerberus_api.sequences`. Si alguna función depende de otros módulos
  de #17 (`release_state`, `sample`, `container_setup`), **elimínala** y declara la desviación en el PR; no portes esos módulos.
- Debe ejecutarse como `uv run python -m cerberus_api.diagnostics` y en el contenedor. Indica en el README qué
  comando correr y qué archivo enviar.
- Privacidad: el reporte no puede incluir `PatientName`, `PatientID`, `PatientBirthDate`, `InstitutionName`,
  `AccessionNumber`, `StudyDate` ni UIDs DICOM, ni secretos (`.env.auth`, tokens). Añade un test que lo compruebe.
- Tras el merge: el orquestador comenta en #17 (`gh pr comment 17 --body "..."`) enlazando el PR nuevo y explicando
  qué se rescató. **Antes de cerrar #17 pregunta al usuario** con AskUserQuestion: cerrar #17 ahora o dejarlo abierto.

**FT-DOC · fine-tuning: estado y pasos futuros** · rama `feat/FTDOC-future-steps` · Vite: no
- Archivos: `docs/TRAINING.md` (solo una sección nueva al final, «Estado y pasos futuros»). Nada más.
- Contenido:
  1. Estado: pipeline FT0–FT5 construido y probado solo con el smoke sintético; ningún entrenamiento real ni validación.
  2. Inventario real: salida de `uv run python -m cerberus_training inventory` sobre `REPO/Data`. Cuántos estudios
     cumplen el perfil estricto y por qué fallan los demás (falta `t2tse`).
  3. Almacenamiento: tamaño medio por estudio (`du -sh REPO/Data/*/*`) multiplicado por el total de estudios de
     CFB-GBM según TCIA. Busca la cifra en la página de la colección y cítala; si no la encuentras, escribe «sin verificar».
     Da también una estimación de la caché de preprocesado.
  4. Pasos futuros en orden, con comandos: descarga, `inventory`, `split`, `prepare`, piloto en GPU (`training-env/`, cu126),
     entrenamiento, evaluación frente a la línea base (EVAL1) e integración (requiere ticket y contratos nuevos).
  5. La decisión abierta de CP-058 (estudios elegibles que fallan en `prepare`).
- Criterio: cada número con su comando o fuente.

### Oleada 2 (tras el merge de la oleada 1)

**ATLAS1 · aplicar la opción elegida** · rama `feat/ATLAS1-<a|b|c>` · Vite 5181 si toca UI
- El orquestador escribe el prompt **después** de la respuesta del usuario, con los archivos exactos según la opción.
  - A: el módulo del atlas, sus tests y el README (sección de Brodmann).
  - B: lo mismo y, si el atlas no puede ir en el repo, su descarga en tiempo de ejecución igual que hoy hace nilearn.
  - C: `frontend/src/components/AreasPanel.tsx`, el texto de los reportes de áreas y el README.
- Criterio común: tabla antes/después de las áreas reportadas por estudio (reutiliza el script de ATLAS0); los tests en
  verde; si cambia la respuesta de `/areas`, se actualizan `schemas.py`, `types.ts` y §7 del plan en el mismo PR
  (regla 1 de AGENTS.md); y la UI dice explícitamente qué espacio y qué limitación tiene el resultado.

**UI1 · botón «Reintentar» del visor** · rama `feat/UI1-retry-button` · Vite 5185
- Archivos: `frontend/src/components/ViewerErrorBoundary.tsx` y `frontend/src/components/viewer.css`. Nada más.
- Cambio: el botón con ancho automático y estilo secundario coherente con el resto del visor. Copia las reglas de
  `.upload-panel .btn-secondary` de `styles.css` (alrededor de la línea 242) en una clase del visor dentro de `viewer.css`.
  Tras un reintento fallido, el foco vuelve al botón.
- Criterio: `verify-viewer-chunk-error.mjs` 5/5 y `verify.mjs` 33/33, uno a uno; capturas antes/después revisadas;
  axe sin violaciones en el fallback.

### Oleada 3 (cierre, después de los checkpoints de las oleadas 1 y 2)

**DOC1 · compactar el HANDOFF** · rama `feat/DOC1-handoff-compact` · Vite: no
- Archivos: `docs/HANDOFF.md` y `docs/PROGRESS.md` (excepción explícita a la regla de no tocarlos).
- Cambio: `HANDOFF.md` §2 queda como estado vivo en ≤ 40 líneas: qué funciona, qué no es válido todavía, pendientes
  priorizados y cómo arrancar. Los párrafos históricos de CP se borran solo si su contenido ya está en la entrada
  CP-NNN de `PROGRESS.md`; si falta algo, se añade antes a esa entrada. Lista en el informe cada párrafo borrado con
  su CP de destino.
- Añade a `PLAN_MVP.md` §12 esta regla, que también es una excepción explícita del ticket: «Antes de escribir un
  checkpoint: `git pull --rebase`; N = mayor CP existente + 1; si el push se rechaza, recalcula N».
- El orquestador **no** escribe checkpoints mientras DOC1 está abierto.

## 6. Ciclo por ticket (orquestador)

1. Worktree: `git worktree add ../Cerberus-wt/<ID> -b <rama> origin/main`. Después, en hc (`--no-notify`): `uv sync`,
   y `npm install` en `frontend` y `tools/e2e` si el ticket usa UI. Comprueba que
   `.venv/bin/python -c "import cerberus_api; print(cerberus_api.__file__)"` apunta al worktree.
2. Prompt `SP/prompts/<id>-impl.md` = el ticket de §5 copiado literalmente + enlace a `common-impl.md`. Lanza con el
   comando de §2.1 según el agente de §2.3.
3. Al terminar: §2.2 (commit, push y PR si no es Claude). Comprueba `gh pr view <n> --json files`: solo los archivos permitidos.
4. Revisor de §2.3 con `SP/prompts/<id>-rev.md`. Hay que repetir los checks, las mediciones y las capturas, y razonar
   la equivalencia o la validez caso por caso.
5. APROBADO → lee tú el informe y `gh pr merge <n> --merge --delete-branch`, luego `git pull --ff-only`.
   CAMBIOS → ronda 2 según §2.2. Si no se resuelve en 2 rondas, pregunta al usuario.
6. Checkpoint: `git pull --rebase`, N = mayor CP + 1. Fila ✅ (hash corto del merge, fecha ISO, agente que
   implementó), entrada `CP-N` en `PROGRESS.md` (qué, archivos, números honestos, desviaciones, pendientes,
   siguiente) y `HANDOFF.md` §2. Commit `chore(progress): CP-N <ID>` y push. Después:
   `grep -o '^### CP-[0-9]*' docs/PROGRESS.md | sort | uniq -d` tiene que salir vacío.
7. Cierra: `hc kill <name>; hc rm <name>` para el implementador y el revisor.

**Checks obligatorios en cada PR:** `uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -q -m "not slow"`,
y `cd frontend && npm run build` si toca frontend.

## 7. Cierre de la ronda

1. En main, con API y worker reiniciados: los checks, `uv run pytest -m slow`, `npm run build` y los 5 e2e uno a uno
   con la carga baja (§3, paso 4). Revisa las PNG.
2. `hc ls` sin hijos tuyos; `git worktree list` solo con el repo y los worktrees que no sean tuyos; borra tus
   artefactos (`dump.rdb`, ramas locales `pr17`, `smoke`).
3. Resumen al usuario: tabla por ticket (agente que implementó / revisó, resultado, números) sin inflar, y qué sigue sin validar.
4. **Para el usuario (no automatizable):** ensayar la demo en la máquina del profesor con el README actualizado,
   ejecutar el diagnóstico de D3R si vuelve el 502 y enviar el archivo que genera.
