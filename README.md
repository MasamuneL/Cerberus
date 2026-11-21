# Cerberus

Análisis exploratorio, visualización 3D y segmentación de glioblastoma sobre el dataset **CFB-GBM** (The Cancer Imaging Archive).

Cerberus es una **app web**: backend **FastAPI + arq/Redis + MONAI** y frontend
**React + Vite + TypeScript + [Niivue](https://github.com/niivue/niivue)** como visor de imagen médica.

Proyecto de Big Data — UDG, 5.º semestre.

La app ya integra el MVP, áreas de Brodmann y dominios funcionales, mejoras de UX/UI, Docker Compose,
autoajuste de recursos y caché HTTP de volúmenes. Estado y trabajo pendiente en
[`docs/HANDOFF.md`](docs/HANDOFF.md); historial en [`docs/PROGRESS.md`](docs/PROGRESS.md).
Los hallazgos del [QA de seguridad y robustez](docs/QA_2026-10-29.md) siguen pendientes de corrección.

**Autenticación de la demo:** A0–A4 incorporan Keycloak persistente, sesiones OIDC, protección de recursos,
roles lector/analista e interfaz de inicio y cierre de sesión. En modo `oidc`, el catálogo exige sesión;
la entrada vuelve a pedir contraseña después del logout. El modo local conserva `off` por defecto.
Variables, restricciones y tickets en
[`PLAN_MVP.md` §17](docs/PLAN_MVP.md#17-autenticación-para-demo-académica--oidc--keycloak).

## Qué incluye

- Backend FastAPI con volumetría GTV, seguimiento RANO, segmentación MONAI y mapeo de áreas.
- Frontend React con visor Niivue, capas, funciones en riesgo y subidas NIfTI/DICOM.
- Docker Compose, pruebas y documentación de contratos y trabajo pendiente.

El notebook marimo original y su auxiliar Mayavi están archivados fuera del repo, en
`../Cerberus-archivo-2026-11-05/referencia/`. Siguen disponibles como referencia de fórmulas;
[ubicación, recuperación desde Git y ejecución](docs/ARCHIVO.md).

> ⚠️ La máscara de referencia del dataset es el **GTV de radioterapia** (puede incluir cavidad de resección y excluye edema), no el "volumen tumoral" genérico.

## Estructura

```
Cerberus/
├── backend/
│   ├── cerberus_api/      # FastAPI (main, routers/, servicios, worker arq)
│   └── tests/             # pytest
├── frontend/              # React + Vite + TS + Niivue
├── docs/
│   ├── PLAN_MVP.md        # plan, contratos y tickets del MVP
│   ├── PROGRESS.md        # bitácora de checkpoints
│   ├── HANDOFF.md         # estado actual y cómo continuar
│   ├── ARCHIVO.md         # referencias archivadas, cuarentena y recuperación
│   ├── QA_UX_UI.md        # evidencia y límites del QA visual
│   └── QA_2026-10-29.md   # hallazgos pendientes de seguridad y robustez
├── compose.yaml           # redis, api, worker y frontend
├── compose.gpu.yaml       # override GPU NVIDIA para el worker (torch cu126/cu130)
├── compose.hybrid.yaml    # override del modo híbrido de Mac Apple Silicon
├── docker/                # Dockerfiles y configuración nginx
├── tools/launch/          # lanzador con detección de hardware (up.sh, up.ps1)
├── tools/e2e/             # verificaciones de UX/UI y smoke Docker
├── storage/               # resultados, uploads, staging (generado, ignorado)
├── AGENTS.md / CLAUDE.md  # instrucciones para agentes de código
├── Data/
│   └── 001/t0/            # muestra versionada con Git LFS
│       ├── 1_t0_t1gd.nii.gz
│       ├── 1_t0_flair.nii.gz
│       ├── 1_t0_gtv.nii.gz
│       └── ...
├── models/                # pesos MONAI y atlas (se descargan al usarlos, ignorado)
├── pyproject.toml
└── uv.lock
```

Archivos de datos: `Data/<paciente>/<tiempo>/<n>_<tiempo>_<secuencia>.nii.gz`
(secuencias: `t1gd`, `t1eg`, `t1tse`, `t2tse`, `t2star`, `flair`, `adc`, `ct`, `rtdose`, `brain_mask`, `gtv`).

## Instalación

Requisitos: Python 3.11, [uv](https://docs.astral.sh/uv/) y [Git LFS](https://git-lfs.com).

```bash
git lfs install
git clone https://github.com/MasamuneL/Cerberus.git
cd Cerberus
uv sync
```

Si clonaste sin LFS, los `.nii.gz` serán punteros de texto; descárgalos con:

```bash
git lfs pull
```

La instalación normal incluye la app web. Para el notebook histórico se habilita el grupo opcional
`notebook`; los comandos y las rutas figuran en [`docs/ARCHIVO.md`](docs/ARCHIVO.md).

## App web

### Qué puerto abrir

| Cómo arrancaste la app | URL de la UI | Servidor que la entrega |
|---|---|---|
| `tools/launch/up.sh` o `up.ps1` | **http://localhost:8080** | nginx, con el frontend compilado por Vite |
| `docker compose up -d --build` | **http://localhost:8080** | nginx, con el frontend compilado por Vite |
| `cd frontend && npm run dev` | **http://localhost:5173** por defecto | servidor de desarrollo de Vite |

Es el mismo frontend React en ambos modos. **Docker no inicia el servidor de desarrollo en 5173**:
si solo levantaste Compose, abre **8080**. El puerto de Docker se puede cambiar con `CERBERUS_HTTP_PORT`.
En desarrollo, Vite necesita seguir ejecutándose en una terminal; la API se inicia aparte en **8000**.
Con Compose, nginx reenvía `/api` al puerto 8000 interno del contenedor, que no se publica en el host.

### Lanzador con detección de hardware (camino recomendado)

El lanzador revisa el sistema operativo, la arquitectura, las CPU y la RAM **que tiene Docker** (`docker info`) y la GPU
NVIDIA (`nvidia-smi`), y levanta el stack con lo mejor que haya. Por dentro ejecuta los mismos comandos de
`docker compose` de las secciones siguientes, que siguen siendo válidos si prefieres arrancarlo a mano.

```bash
tools/launch/up.sh               # macOS, Linux y WSL2: detecta y levanta
tools/launch/up.sh --dry-run     # muestra los archivos compose, las variables y los comandos, sin ejecutar nada
tools/launch/up.sh down          # baja el stack (y el worker nativo en el modo híbrido)
```

En Windows (PowerShell 5.1 o 7), con las mismas opciones:
`powershell -ExecutionPolicy Bypass -File tools\launch\up.ps1 --dry-run`.

**Qué usa cada SO**

| Equipo | Qué levanta | Segmentación MONAI | Registro ANTs (áreas) |
|---|---|---|---|
| Mac Apple Silicon | modo híbrido: `compose.yaml` + `compose.hybrid.yaml` + worker nativo con `uv` | MPS (GPU de Apple) | nativo arm64 |
| Mac Apple Silicon con `--no-hybrid` | `compose.yaml` (backend `linux/amd64` bajo Rosetta) | CPU emulada | CPU emulada; sugiere `--fast` |
| Mac Intel | `compose.yaml` | CPU | CPU |
| Linux, WSL2 o Windows con NVIDIA (cc 5.0–9.x, driver ≥ 525) | `compose.yaml` + `compose.gpu.yaml`, torch `cu126` | CUDA (fp16) | CPU |
| Lo mismo con Blackwell (RTX 50xx, cc ≥ 10.0) y driver ≥ 580 | `compose.yaml` + `compose.gpu.yaml`, torch `cu130` | CUDA (fp16) | CPU |
| Blackwell con driver < 580 | `compose.yaml` y un aviso para actualizar el driver | CPU | CPU |
| Linux, WSL2 o Windows sin NVIDIA (o con `--cpu`) | `compose.yaml` | CPU | CPU |
| Linux o Windows arm64 (también con NVIDIA: GB10/DGX Spark, Grace, Jetson) | `compose.yaml` (backend `linux/amd64` emulado; la GPU se ignora con un aviso, porque CUDA no funciona emulado) | CPU emulada | CPU emulada; sugiere `--fast` |

GPU NVIDIA: en Linux hace falta [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
(el lanzador comprueba el runtime `nvidia` en `docker info` y, si falta, avisa y usa CPU); en Windows basta Docker
Desktop con WSL2 y el driver de Windows. La imagen GPU se etiqueta `cerberus-backend:<variante>` y pesa ~7 GB.

Además del modo, el lanzador fija estas variables **solo si no las definiste tú** (en la terminal o en `.env`):

| Variable | Valor del lanzador |
|---|---|
| `CERBERUS_WORKER_MEM_LIMIT` | `clamp(RAM de Docker − 2 GB, 5 GB, 12 GB)`; con GPU el mínimo es 6 GB (contexto CUDA). Con menos de 5 GB libres para el worker avisa (pico ~4.2 GB con 001/t0). No aplica al modo híbrido. Ojo: con Docker Desktop de 8 GB (~7.65 GiB) queda en **5g**, no en el `6g` que usa `docker compose up` a mano |
| `CERBERUS_TORCH_VARIANT` | `cu126` o `cu130` según la compute capability y el driver (lo lee `compose.gpu.yaml`). El mínimo de 525 para cu126 se apoya en la *minor version compatibility* de CUDA 12: basta para las ruedas, pero sin JIT de PTX |
| `CERBERUS_REGISTRATION` | `fast` con `--fast`. Con ≤ 4 CPU en Docker o con emulación lo sugiere sin aplicarlo |
| `CERBERUS_UID` / `CERBERUS_GID` | en Linux y WSL2, `$(id -u)` / `$(id -g)` |

Precedencia: **entorno de la terminal > `.env` de la raíz > valor del lanzador > default de `compose.yaml`**. Compose
lee `.env` por su cuenta; el lanzador lo lee también para no exportar encima nada de lo que contiene y para pasar al worker
nativo (que no lee `.env`) los mismos `CERBERUS_*_PATH`, `CERBERUS_REDIS_PORT`, `CERBERUS_CPU_THREADS`,
`CERBERUS_REGISTRATION`, `CERBERUS_MAX_UPLOAD_MB` y `CERBERUS_MAX_ZIP_UNCOMPRESSED_MB`. Dos límites: el lanzador solo
lee el `.env` de la raíz (si usas `COMPOSE_ENV_FILES` o `--env-file`, define ahí también lo que no quieras que proponga
él), y una variable vacía en la terminal (`CERBERUS_X=`) cuenta como tuya: el informe la muestra vacía aunque Compose
aplique su default (`:-…`).

| Opción | Efecto |
|---|---|
| `--dry-run` | imprime la detección, los archivos compose, las variables (con su origen), los avisos y los comandos |
| `--cpu` | ignora la GPU NVIDIA |
| `--no-hybrid` | en Mac Apple Silicon usa el worker de Docker (Rosetta) en vez del nativo |
| `--fast` | aplica `CERBERUS_REGISTRATION=fast` |
| `--foreground` | modo híbrido: el worker nativo corre en la terminal (Ctrl+C lo detiene) en vez de en segundo plano |
| `down` | detiene el worker nativo por su PID y baja el stack con los mismos `-f` del último arranque |

En el modo híbrido el worker nativo queda en segundo plano con PID y log en `storage/launch/` (`worker.pid` y
`worker.log`); `storage/launch/compose-files` guarda los `-f` para el `down`. Hace falta `uv` en el `PATH` (o
`CERBERUS_UV=/ruta/a/uv`); antes de arrancarlo corre `uv sync --locked`, que se detiene si `uv.lock` no coincide con
`pyproject.toml`. Si el worker ya corre, `up` lo reutiliza: para que cargue código nuevo, `down` y luego `up`. Si el puerto de Redis (6379) está ocupado, el lanzador se detiene y pide
`CERBERUS_REDIS_PORT=6390` u otro libre. Para varias copias en paralelo, cambia también `COMPOSE_PROJECT_NAME`,
`CERBERUS_HTTP_PORT` y `CERBERUS_KEYCLOAK_HTTP_PORT`.

### Opción rápida: Docker Desktop (recomendada para usarla)

Son los comandos que ejecuta el lanzador en el caso CPU, por si prefieres arrancar a mano.

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) con Compose **≥ 2.24** y **≥ 8 GB de RAM** asignados
(Settings → Resources) y la muestra `Data/001` descargada con Git LFS. En Mac con Apple Silicon activa
*Use Rosetta for x86_64/amd64 emulation* (Settings → General): el backend es `linux/amd64` porque ANTs no publica
wheel ARM para Linux.

```bash
docker compose up -d --build      # primer build: varios minutos (torch CPU + ANTs)
docker compose ps -a              # seis servicios healthy; setup-secrets y setup-identity terminan con código 0
open http://localhost:8080        # la app
docker compose logs -f worker     # ver jobs de segmentación / áreas
docker compose down               # parar conservando cuentas, claves y resultados
```

El comando incluye login, Keycloak, PostgreSQL y la cuenta **demo / demo**; no requiere Python en el host,
bootstrap manual, overlay ni configuración en la consola de Keycloak. En Docker Desktop aparece el proyecto
**cerberus** con seis servicios persistentes y dos inicializadores que terminan con código 0. Se publican
`127.0.0.1:8080` (nginx) y `127.0.0.1:8081` (Keycloak); `/api` se reenvía a la API y Redis queda en la red interna. `Data/`, `storage/` y `models/` se montan desde el repo,
así que los resultados se comparten con el modo de desarrollo.

Si el frontend reinicia con `exec /usr/local/bin/cerberus-nginx: no such file or directory`, puede haberse
construido con finales de línea Windows (CRLF). El build normaliza ese script desde la corrección D2b.
Tras actualizar el repositorio, reconstruye y recrea el servicio:

```bash
git pull --ff-only
docker compose up -d --build --force-recreate frontend
```

Los comandos anteriores con `--env-file .env.auth -f compose.yaml -f compose.auth.yaml` siguen siendo válidos,
pero ya no son necesarios. Abre `http://localhost:8080`. Si aparece «Servicio no disponible», comprueba
`docker compose ps -a` y `docker compose logs --tail=100 setup-secrets setup-identity api frontend`:
la pantalla indica un fallo al consultar configuración o sesión, no identifica por sí sola la causa.

| Variable (opcional) | Default | Para qué |
|---|---|---|
| `CERBERUS_HTTP_PORT` | 8080 | puerto local de la app |
| `CERBERUS_CPU_THREADS` | auto | hilos de MONAI/ANTs; `auto` = máx(1, mín(floor(CPUs) − 1, 8)) según las CPU disponibles; un entero positivo lo fija (ver `GET /api/system`) |
| `CERBERUS_REGISTRATION` | full | registro ANTs de las áreas de Brodmann: `full` (referencia) o `fast` (más rápido, resolución menor; el reporte lo anota «(rápido)»). También sirve en desarrollo nativo; otro valor impide arrancar la API/el worker |
| `CERBERUS_WORKER_MEM_LIMIT` / `CERBERUS_API_MEM_LIMIT` | 6g / 2g | límites de memoria (el lanzador calcula el del worker) |
| `CERBERUS_TORCH_VARIANT` | cu126 | solo con `compose.gpu.yaml`: torch `cu126` o `cu130` (Blackwell, driver ≥ 580) |
| `CERBERUS_REDIS_PORT` | 6379 | solo con `compose.hybrid.yaml`: puerto de Redis en `127.0.0.1` |
| `CERBERUS_DATA_PATH` / `CERBERUS_MODELS_PATH` | `./Data` / `./models` | carpetas del host para datos y modelos |
| `CERBERUS_STORAGE_PATH` | `./storage` | separar los resultados de Docker de los de desarrollo |
| `CERBERUS_UID` / `CERBERUS_GID` | 1000 | solo en Linux: `$(id -u)` / `$(id -g)` |

**Rendimiento** (Mac de 14 CPU, Docker con CPU bajo Rosetta, 4 hilos): segmentación MONAI ~2 min (92 s con 8 hilos;
en desarrollo con MPS ~18 s), mapeo de áreas ~1.5 min en frío y ~30 s con el registro en caché. Pico del worker
~4.2 GiB. La segmentación de referencia coincide con la de desarrollo (001/t0: Dice TC 0.857);
el registro ANTs puede variar entre ejecuciones con varios hilos. Son mediciones del 2026-10-29,
no tiempos garantizados para cualquier equipo o estudio.

Smoke test de la versión Docker: `cd tools/e2e && npm ci && CERBERUS_UI=http://localhost:8080 node verify-docker.mjs`.

### Mac Apple Silicon: modo híbrido

Docker Desktop no expone Metal (MPS) a los contenedores y ANTs no publica wheel Linux arm64, así que el worker de
Docker corre en CPU bajo Rosetta. En el modo híbrido **API, Keycloak, Redis y frontend siguen en Docker**, pero el
worker corre **nativo** con `uv`: MONAI usa MPS y ANTs usa su wheel `macosx_arm64`. Comparten `Data/`, `storage/` y
`models/` por bind mount y la cola de Redis, así que la app se usa igual que en el modo normal.

Requisitos: los de la opción rápida, más [uv](https://docs.astral.sh/uv/) y los modelos descargados en `models/`.
`tools/launch/up.sh` hace estos dos pasos solo (worker en segundo plano; `tools/launch/up.sh down` para todo). A mano:

```bash
# Paso 1: stack en Docker sin worker (compose.hybrid.yaml lo desactiva y publica Redis solo en 127.0.0.1)
docker compose -f compose.yaml -f compose.hybrid.yaml up -d --build
docker compose -f compose.yaml -f compose.hybrid.yaml ps           # sin servicio «worker»

# Paso 2: worker nativo, en otra terminal y con las mismas rutas que los bind mounts
uv sync
CERBERUS_REDIS_URL="redis://127.0.0.1:${CERBERUS_REDIS_PORT:-6379}/0" \
CERBERUS_DATA_DIR="${CERBERUS_DATA_PATH:-./Data}" \
CERBERUS_STORAGE_DIR="${CERBERUS_STORAGE_PATH:-./storage}" \
CERBERUS_MODELS_DIR="${CERBERUS_MODELS_PATH:-./models}" \
uv run python -m cerberus_api.worker
```

Comprobación: con la sesión iniciada, `http://localhost:8080/api/system` debe mostrar `"platform": "darwin/arm64"`,
`"device": "mps"` y `"in_container": false`. Si aparece `linux/x86_64 (emulado…)`, respondió el worker de Docker:
revisa que `ps` no lo liste y que no lo hayas levantado sin el override.

- **Parar:** `Ctrl+C` en el worker y `docker compose -f compose.yaml -f compose.hybrid.yaml down`. Usa siempre los
  mismos dos `-f`: sin el override, `docker compose up` vuelve a crear el worker de Docker, y dos workers sobre la misma
  cola se repartirían los jobs. Si arrancaste el worker de Docker con `--profile docker-worker`, añade también
  `--profile docker-worker` al `down` para que no quede ese contenedor.
- **Volver al worker de Docker:** detén el nativo y levanta el perfil con
  `docker compose -f compose.yaml -f compose.hybrid.yaml --profile docker-worker up -d worker`.
- **Puerto de Redis:** por defecto 6379. Si ya corre un `redis-server` local (modo desarrollo) o Docker avisa de que el
  puerto está ocupado, exporta `CERBERUS_REDIS_PORT=6390` **en la misma terminal** antes de ambos pasos.
- **Variables compartidas:** `CERBERUS_HTTP_PORT`, `CERBERUS_DATA_PATH`, `CERBERUS_STORAGE_PATH`, `CERBERUS_MODELS_PATH` y
  `CERBERUS_CPU_THREADS` se leen igual en ambos lados. El worker nativo no lee `.env`: las expresiones del paso 2 repiten
  los defaults de Compose, y si defines esas variables solo en `.env`, expórtalas también en la terminal del worker.
- **Permisos:** el worker escribe `storage/results/` con tu usuario y la API de Docker lee esos archivos y puede crear
  otros en las mismas carpetas: Docker Desktop traduce el propietario en los bind mounts, así que no hace falta
  `CERBERUS_UID` (comprobado con UID 1000 y 501).

> **Aviso de seguridad:** Redis corre **sin contraseña**. `compose.hybrid.yaml` lo publica solo en
> `127.0.0.1:${CERBERUS_REDIS_PORT:-6379}` (nunca en `0.0.0.0`), pero cualquier proceso de este Mac puede encolar jobs
> o leer la cola mientras el stack esté arriba. No cambies esa IP ni expongas el puerto en una red compartida.

**Rendimiento** (001/t0; Mac de 14 CPU y 36 GB; Docker con 14 CPU y 8 GB; 8 hilos; 2026-11-20). Se midió con la
máquina bajo carga (load average 15–30 por otros procesos), así que son cotas superiores y no tiempos garantizados.
Cada medición se hizo dos veces; el registro «en frío» se obtuvo apartando la caché `results/001/t0/mni/`:

| Paso | Worker nativo (MPS + ANTs arm64) | Worker Docker + Rosetta (CPU) |
|---|---|---|
| Segmentación MONAI | 34 s la primera (carga del modelo), 16 s la segunda | 87 s y 90 s |
| Mapeo de áreas en frío | 38 s y 26 s | 67 s y 70 s |
| Mapeo de áreas con registro en caché | 9 s | 31 s |

La segmentación coincide con la de Docker (001/t0: Dice TC 0.857).

### Diagnóstico de un 502

Desde la raíz del proyecto, captura el estado de los servicios y genera el reporte en un contenedor
temporal. Si arrancaste con archivos Compose adicionales, usa los mismos argumentos `-f` en ambos
comandos. La imagen de la API debe estar construida con esta versión de Cerberus.

```bash
cerberus_estado=$(docker compose ps --all --orphans=false --format json) &&
  (umask 077; set -C; printf '%s\n' "${cerberus_estado:-[]}" |
    docker compose run --rm --no-deps --pull never -T --entrypoint python api \
      -m cerberus_api.diagnostics --compose-stdin > cerberus-diagnostico.json)
```

En desarrollo local, o si Docker no está disponible, comprueba la muestra y el acceso a las carpetas
con el entorno local de Python del proyecto.

```bash
uv run python -m cerberus_api.diagnostics --export cerberus-diagnostico.json
```

Comparte `cerberus-diagnostico.json`. Contiene códigos de diagnóstico, nombres de servicios predefinidos
y acciones sugeridas. El comando sale con código 1 si detecta algún error y genera el reporte igualmente.
Si el archivo ya existe, usa otro nombre.

### Identidad, sesiones y permisos de la demo (A1–A4)

**Acceso a la demo local:** usuario `demo`, contraseña `demo`.
Compose genera tres claves aleatorias una sola vez en volúmenes locales separados y prepara Keycloak
antes de arrancar la API. PostgreSQL recibe únicamente su clave, la API únicamente el secreto del cliente,
y Keycloak las claves que necesita. No se versionan ni se imprimen. `setup-identity` crea la cuenta de
prueba con rol `analyst` si falta; una cuenta existente conserva contraseña, roles y estado.

Los volúmenes `auth-db-data`, `keycloak-data`, `auth-db-secret`, `keycloak-admin-secret` y
`oidc-client-secret` conservan identidad y claves entre arranques. `docker compose down` los mantiene;
`down -v` los elimina. Las imágenes y resultados de estudios siguen en los montajes habituales.

Si ya utilizabas `.env.auth`, consérvalo en la raíz: el inicializador lo lee como fuente opcional y adopta
los mismos secretos. No genera claves nuevas para una base existente cuando faltan las anteriores ni
sobrescribe claves persistidas. El overlay `compose.auth.yaml` queda como compatibilidad. Los scripts
`tools/auth/bootstrap.py` y `sync_realm.py` siguen disponibles para operaciones manuales, sin ser pasos
necesarios del arranque normal.

Si 8080 está ocupado, por ejemplo por `openshell-gatew`, puedes arrancar en otro puerto:

```bash
CERBERUS_HTTP_PORT=8082 docker compose up -d --build
```

Abre entonces **http://localhost:8082**. Para conservarlo entre terminales, escribe
`CERBERUS_HTTP_PORT=8082` en `.env` y utiliza el comando normal. El origen público y el callback exacto
se derivan de ese puerto y se actualizan automáticamente, incluso con un realm ya existente;
no necesitas editar Keycloak. Un `CERBERUS_APP_ORIGIN` explícito tiene prioridad y debe corresponder
al origen que realmente usa el navegador. Las opciones públicas de `.env.auth` solo participan en la
interpolación si se pasa ese archivo explícitamente con `--env-file`.

El cliente exige Authorization Code con PKCE S256. `setup-identity` gestiona solo `redirectUris` y
`webOrigins` de `cerberus-web`, además de la presentación del realm y la cuenta demo con SKIP.
Conserva secreto del cliente, PKCE, límites de sesión, cuentas y configuración ajena. La consola
administrativa de Keycloak no es necesaria para usar la cuenta de prueba; esta cuenta no tiene roles
administrativos. El registro público y el password grant del cliente están desactivados.

El lector consulta estudios; solo el analista puede subir y procesar. Jobs e ingestas pendientes son
privados para su identidad; los estudios finales forman un catálogo compartido. El modo de desarrollo
nativo con Vite sigue disponible; el Compose predeterminado utiliza autenticación.

«Recordarme» conserva la sesión de Keycloak en ese navegador según sus límites de proveedor. El login de
Cerberus mantiene `prompt=login`, por lo que volver a entrar sigue exigiendo credenciales aunque se marque
la casilla. Esta opción no amplía la sesión de Cerberus: sus límites predeterminados siguen siendo
**1800 s sin actividad y 3600 s en total**. Cerrar Cerberus invalida su sesión local; no promete cerrar
las sesiones de Keycloak o de otras aplicaciones.

| Configuración de identidad en Compose | Default |
|---|---|
| `CERBERUS_KEYCLOAK_HTTP_PORT` | `8081`, solo loopback |
| `CERBERUS_KEYCLOAK_ADMIN_USERNAME` | `cerberus-admin` |
| `CERBERUS_APP_ORIGIN` | `http://localhost:${CERBERUS_HTTP_PORT:-8080}` |
| Issuer público | `http://localhost:8081/realms/cerberus` |
| Backchannel de API en Docker | `http://keycloak:8080/realms/cerberus` |

La metadata conserva el issuer público y ofrece token/JWKS por la red interna; no se desactivan las
validaciones OIDC. PostgreSQL no publica puertos y solo comparte su red privada con Keycloak. Los datos
de identidad viven en volúmenes `auth-db-data` y `keycloak-data`; el catálogo y las imágenes siguen en disco.
Para parar, usa `docker compose down`, sin `-v` si quieres conservar cuentas y claves. `start-dev` y HTTP pertenecen exclusivamente a esta demo local.

Con Compose, puedes iniciar sesión en **http://localhost:8080/api/auth/login**. FastAPI usa
Authorization Code + PKCE S256 con Authlib y verifica firma RS256, issuer, audience, expiración, nonce
y `azp` antes de crear la sesión. Una cuenta sin roles de Cerberus recibe 403. El navegador conserva
solo una cookie opaca `HttpOnly`/`SameSite=Lax`, sin tokens OIDC en almacenamiento del navegador.

`GET /api/auth/me` devuelve roles, vencimiento efectivo y token CSRF. `POST /api/auth/logout` requiere
`Origin` de la app y ese token en `X-CSRF-Token`: invalida Redis y borra cookies; cierra la sesión de
Cerberus, no la de otras aplicaciones del proveedor. La inactividad caduca a 30 minutos y la duración
absoluta a 60; Compose admite `CERBERUS_AUTH_IDLE_TIMEOUT_SECONDS` y
`CERBERUS_AUTH_ABSOLUTE_TIMEOUT_SECONDS` para configurarlas. Redis caído produce 503; Keycloak caído
impide nuevos logins, mientras las sesiones válidas continúan hasta vencer. Respuestas de auth: `no-store`.
En modo local `off`, `/api/auth/config` informa el modo y las otras rutas de auth devuelven 404.

Las mutaciones OIDC requieren `Origin` autorizado y `X-CSRF-Token` de `/api/auth/me`; los permisos se
comprueban antes de leer el body, acceder a disco o responder 304. JSON autenticado usa `no-store`;
NIfTI usa `private, no-cache`, con sesión comprobada en cada GET/HEAD. `/docs`, `/redoc` y `/openapi.json`
se deshabilitan en OIDC. Logout impide nuevas descargas; no borra archivos descargados ni cachés existentes.
En modo `off`, toda mutación requiere `X-Cerberus: 1`; si llega `Origin`, debe estar autorizado. El cliente
web lo añade automáticamente. Ejemplo CLI local: `curl -H 'X-Cerberus: 1' -X POST ...`.

API y nginx solo aceptan Host de loopback (la API admite además el host de `CERBERUS_APP_ORIGIN`).
Si Vite usa otro puerto, configura `CERBERUS_APP_ORIGIN` y `CERBERUS_CORS_ORIGINS` con ese origen real;
por ejemplo, `http://localhost:5180` en ambos. El callback del cliente de Keycloak también debe coincidir.

El worker se inicia con `uv run python -m cerberus_api.worker`: cubre también fallos tempranos de arq
(expiración, deserialización y reintentos agotados) al alinear el TTL de propietarios con sus resultados.
La CLI `arq --check cerberus_api.worker.WorkerSettings` sigue disponible para salud.

Si Redis pierde la propiedad de una ingesta, la API devuelve 404; no la asigna a quien conozca su UUID.
Para descartar una ingesta huérfana, para primero **worker y API** para evitar carreras. En desarrollo nativo,
con sus mismas variables de rutas, ejecuta el bloque siguiente con el UUID concreto revisado por el operador:

```bash
CERBERUS_ORPHAN_UPLOAD='<uuid-hex-de-32-caracteres>' uv run python - <<'PYTHON'
import os
import shutil
from cerberus_api.config import get_settings
from cerberus_api.staging import upload_dir, validate_upload_id
settings = get_settings()
upload_id = validate_upload_id(os.environ["CERBERUS_ORPHAN_UPLOAD"])
shutil.rmtree(upload_dir(settings.staging_dir, upload_id), ignore_errors=True)
(settings.tmp_dir / f"{upload_id}.zip").unlink(missing_ok=True)
PYTHON
```

En Docker, detén `api worker` con ambos archivos Compose y ejecuta el mismo Python mediante
`docker compose --env-file .env.auth -f compose.yaml -f compose.auth.yaml run --rm --no-deps -T api python -`,
pasando el UUID con `-e CERBERUS_ORPHAN_UPLOAD=<uuid>` antes de `api` y conservando las variables de mounts.
Después reinicia `api worker`. No borres resultados ni estudios finales para limpiar una ingesta pendiente.

### Modo desarrollo: requisitos

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node `^20.19.0 || >=22.12.0` (según Vite en `frontend/package-lock.json`) y npm
- Redis (`brew install redis`)
- [Git LFS](https://git-lfs.com) (para la muestra en `Data/001`)

### Arranque (4 terminales, desde la raíz)

```bash
uv sync                                                    # una vez: deps Python
redis-server                                               # terminal 1
uv run python -m cerberus_api.worker              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --reload-dir backend --port 8000  # terminal 3: API
cd frontend && npm install && npm run dev                  # terminal 4: UI
```

- UI de desarrollo (con Vite ejecutándose): <http://localhost:5173>. Si usas Docker: <http://localhost:8080>.
- Documentación interactiva de la API: <http://localhost:8000/docs>
- Alternativa para la API, con host y puerto tomados del entorno: `uv run python -m cerberus_api.serve --reload`.

#### Puertos configurables

Si algún puerto está ocupado, elígelos con variables de entorno (sin definir, todo queda como arriba):

| Variable | Default | Uso |
|---|---|---|
| `CERBERUS_API_HOST` | `127.0.0.1` | host del lanzador `python -m cerberus_api.serve` |
| `CERBERUS_API_PORT` | `8000` | puerto de la API y destino del proxy `/api` de Vite |
| `CERBERUS_UI_PORT` | `5173` | puerto de Vite; deriva `CERBERUS_CORS_ORIGINS` y `CERBERUS_APP_ORIGIN` si no se fijan |
| `CERBERUS_REDIS_URL` | `redis://localhost:6379` | para otro puerto de Redis: `redis-server --port N` |

Vite y la API deben ver las mismas variables: expórtalas en la sesión (`export CERBERUS_API_PORT=8001`) o
anteponlas a cada comando. El worker solo necesita `CERBERUS_REDIS_URL`.

```bash
export CERBERUS_API_PORT=8001 CERBERUS_UI_PORT=5174
redis-server --port 6380                                   # terminal 1
CERBERUS_REDIS_URL=redis://localhost:6380 uv run python -m cerberus_api.worker           # terminal 2
CERBERUS_REDIS_URL=redis://localhost:6380 uv run python -m cerberus_api.serve --reload   # terminal 3
cd frontend && npm run dev                                 # terminal 4: UI en :5174, proxy a :8001
```

Los scripts de `tools/e2e/` usan `CERBERUS_UI` o, si falta, `http://localhost:${CERBERUS_UI_PORT:-5173}`.

### Arquitectura

El siguiente diagrama corresponde al modo desarrollo. Con Docker, el navegador entra por nginx en
**8080**, que sirve el frontend compilado y reenvía `/api` a la API interna.

```
Navegador (React + Niivue, :5173)
   │  /api/*  (proxy de Vite en dev)
   ▼
FastAPI (:8000) ──lee/escribe──► Data/   storage/
   │ encola (arq)
   ▼
Redis (:6379) ◄── worker arq ──► MONAI SegResNet (torch, cpu/mps/cuda)
                         └─────► dcm2niix (conversión DICOM)
                         └─────► ANTs + atlas Talairach (áreas de Brodmann)
```

### Funcionalidades

- Lista de estudios (paciente / tiempo) detectados en `Data/`, con resultados en `storage/results/`,
  volumen del GTV, tendencia longitudinal y badges de segmentación y áreas.
- Visor multiplanar (axial/coronal/sagital) y 3D con Niivue; capas de GTV, MONAI y áreas con visibilidad
  y opacidad ajustables, centrado en GTV y lectura de coordenadas, intensidades y etiquetas bajo el cursor.
- Volumetría (planimetría vs ABC/2) y evaluación **RANO 2.0** longitudinal por paciente.
- Segmentación **MONAI** (`brats_mri_segmentation`) como job asíncrono (arq), con estados y etapas de cálculo.
- Mapeo de **áreas de Brodmann y estructuras subcorticales** mediante registro ANTs al atlas Talairach:
  solapamiento con GTV y WT cuando existe, porcentaje del área, distancia y funciones por hemisferio.
- Resumen de **funciones en riesgo** por dominio (lenguaje, motor, sensitivo, visión, etc.), con niveles
  Afectado, Comprometido y En vigilancia; foco en un área desde la tabla o los chips del resumen.
- Pestañas de Volumetría, Segmentación, Áreas y Longitudinal; navegación con teclado, tipografía IBM Plex
  y paleta fría para áreas. El [QA de UX/UI](docs/QA_UX_UI.md) documenta el alcance y los límites de accesibilidad.
- Indicador de CPU/GPU, hilos y memoria en Segmentación y Áreas, con avisos y duraciones estimadas.
- Subida de volúmenes NIfTI.
- Ingesta de ZIP DICOM con conversión mediante dcm2niix, vista previa y confirmación de series;
  consulta las [limitaciones de privacidad](#privacidad-y-limitaciones-conocidas) antes de subir datos.

El mapeo de áreas es una estimación educativa: no sustituye fMRI, tractografía ni mapeo cortical
intraoperatorio. Con lesiones grandes, el registro pierde precisión.

### Cómo se estiman las áreas de Brodmann

Cerberus adapta un atlas anatómico al espacio de cada paciente mediante **registro de imágenes**.
Este proceso es independiente de MONAI: SegResNet segmenta regiones de lesión; el registro ubica
las etiquetas del atlas sobre la RM. Las áreas y funciones mostradas son estimaciones educativas.

| Herramienta | Función |
|---|---|
| Nilearn | Obtiene el atlas Talairach-Brodmann, nivel `ba` en espacio Talairach, y la plantilla MNI152 con su máscara cerebral |
| ANTsPy (`antspyx`) / ANTs SyN | Calcula alineación afín y deformación local entre paciente y plantilla |
| NiBabel | Lee, remuestrea y guarda NIfTI conservando coordenadas físicas |
| NumPy y SciPy | Calculan volúmenes, intersecciones y distancias |
| Niivue | Visualiza el mapa de áreas sobre las imágenes del estudio |

**Adaptación a cada cerebro:**

1. Selecciona una T1, preferentemente sin contraste (`t1eg`, después `t1tse`; finalmente `t1gd`).
   Si existe `brain_mask`, la aplica. Remuestrea a 1.5 mm isotrópicos para acelerar el registro.
2. Registra la T1 contra MNI152 de 1 mm con **ANTs SyN**: una etapa afín ajusta posición,
   orientación, escala y cizallamiento; una deformación local ajusta diferencias anatómicas.
3. Excluye el GTV y un margen de **5 mm** de la función de costo en todas las etapas para reducir
   la influencia de la lesión sobre el ajuste. Esto no garantiza reconstruir la anatomía desplazada.
4. Proyecta el atlas Talairach a MNI152 mediante la afín `icbm_other2tal` de Lancaster et al. (2007).
   Para muestrear las etiquetas, ANTs lleva cada punto del grid del paciente a MNI152 con las
   transformaciones inversas del registro y luego a Talairach con la afín. El atlas se separa por
   hemisferios en Talairach y se muestrea una sola vez con `genericLabel`.
5. Guarda `brodmann.nii.gz` con el grid y la afín de la referencia del visor, preferentemente `t1gd`.
   Reutiliza el registro MNI cuando coinciden las entradas y los parámetros. Se presupone que las
   series están corregistradas. Al volver a calcular las áreas, se reemplazan el mapa y el reporte anteriores.

**Cálculos por área:** GTV y etiquetas se llevan al mismo grid; las máscaras se remuestrean con
vecino más cercano cuando hace falta. Con tamaños de vóxel `sx`, `sy`, `sz` en mm:

| Resultado | Cálculo |
|---|---|
| Volumen del área, cm³ | `n_vóxeles_del_área × sx × sy × sz / 1000` |
| Intersección con GTV, cm³ | `n_vóxeles_compartidos × sx × sy × sz / 1000` |
| Porcentaje del área solapada | `100 × n_vóxeles_compartidos / n_vóxeles_del_área` |
| Distancia mínima, mm | Transformada de distancia euclidiana con spacing físico; cero si hay intersección |

El reporte incluye áreas solapadas con GTV y áreas cercanas hasta **10 mm**. Cuando existe
segmentación MONAI, añade intersección con WT. El atlas etiqueta regiones corticales y estructuras
subcorticales; el porcentaje corresponde al territorio etiquetado, no a todo el tejido cerebral.

Ejemplo: un área de 10 cm³ comparte 2 cm³ con GTV; el solapamiento es **20 % del área**.
Ese valor no representa un 20 % de pérdida funcional. Las funciones asociadas proceden de
[`area_functions.json`](backend/cerberus_api/data/area_functions.json), una base bibliográfica
con diferencias por hemisferio cuando corresponde; no se miden funciones individuales mediante RM estructural.

La afín de Lancaster ajusta globalmente las coordenadas de un atlas determinista derivado de un único cerebro.
`icbm_other2tal` carece de validación específica para la plantilla ICBM152 2009a no lineal simétrica de
Cerberus. El resultado se interpreta con cautela como una estimación anatómica educativa.
[Método y alcance de la validación de BrainMap](https://www.brainmap.org/icbm2tal/).

La ausencia de `brain_mask`, disponer solo de T1 con contraste y un GTV grande pueden reducir la calidad
del registro. Un mapa alineado visualmente no demuestra localización funcional individual ni sustituye
fMRI, tractografía o mapeo cortical intraoperatorio.

Implementación: [`atlas.py`](backend/cerberus_api/atlas.py) y [`areas.py`](backend/cerberus_api/areas.py).
Referencias: [registro y transformaciones ANTsPy](https://antspy.readthedocs.io/en/latest/registration.html),
[atlas Talairach de Nilearn](https://nilearn.github.io/stable/modules/generated/nilearn.datasets.fetch_atlas_talairach.html)
y [definición del espacio en el código de Nilearn](https://github.com/nilearn/nilearn/blob/main/nilearn/datasets/atlas.py).

### Vista 3D y superficie del GTV

Selecciona **3D** (tecla `5`) para ver la superficie roja del GTV sobre el volumen. El panel permite
ocultar el cráneo cuando existe una máscara cerebral compatible con la secuencia, ajustar iluminación, bordes y silueta, cambiar
la opacidad y visibilidad de la malla a través del cerebro, activar un plano de corte y elegir
orientaciones de cámara. **Restablecer** recupera los ajustes iniciales de la vista 3D.

La superficie se calcula en el navegador a resolución nativa para conservar focos pequeños y se
suaviza para su visualización. El volumen indicado como «malla» es orientativo: la medida de referencia
sigue siendo **Volumetría**, calculada sobre los vóxeles del GTV. Al volver a cortes 2D se recuperan
el overlay del GTV y la imagen sin modulación de la máscara cerebral.

### Atajos del visor

| Tecla | Acción |
|---|---|
| `1` / `2` / `3` / `4` / `5` | Multiplanar / axial / coronal / sagital / 3D |
| `G` | Centrar en el GTV |
| `S` | Mostrar u ocultar segmentación MONAI |
| `A` | Mostrar u ocultar áreas de Brodmann |
| `?` / `Esc` | Mostrar ayuda / cerrar ayuda |

Los atajos no se activan con el foco en campos de texto o selectores. `Esc` aquí cierra la ayuda del visor;
el modal de subida tiene un [fallo conocido de foco y cierre](docs/QA_2026-10-29.md#4-frontend).

### Endpoints principales (prefijo `/api`)

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/health` | Estado del servicio |
| GET | `/api/system` | Recursos del worker; si no ha reportado o Redis falla, recursos de la API con aviso |
| GET | `/api/studies` | Lista de estudios |
| GET | `/api/studies/{patient}/{timepoint}` | Detalle de un estudio (secuencias disponibles) |
| GET/HEAD | `/api/studies/{patient}/{timepoint}/files/{name}.nii.gz` | Descarga una secuencia, `monai_seg` o `brodmann`; admite revalidación 304 |
| GET | `/api/studies/{patient}/{timepoint}/volumetry` | Volumetría GTV (planimetría, ABC/2) |
| GET | `/api/patients/{patient}/longitudinal` | Serie longitudinal + clasificación RANO 2.0 |
| POST | `/api/studies/{patient}/{timepoint}/segmentation` | Encola la segmentación MONAI (202) |
| GET | `/api/studies/{patient}/{timepoint}/segmentation` | Resultado de la segmentación |
| POST | `/api/studies/{patient}/{timepoint}/areas` | Encola el mapeo de áreas (202); requiere GTV y secuencia T1 |
| GET | `/api/studies/{patient}/{timepoint}/areas` | Reporte de áreas y funciones asociadas |
| GET | `/api/jobs/{job_id}` | Estado / progreso de un job |
| POST | `/api/uploads` | Sube NIfTI (201) o ZIP DICOM (202, ingesta encolada) |
| GET | `/api/uploads/{upload_id}` | Estado de una ingesta DICOM |
| GET/HEAD | `/api/uploads/{upload_id}/series/{index}.nii.gz` | Vista previa de una serie convertida |
| POST | `/api/uploads/{upload_id}/confirm` | Confirma el mapeo de series → crea el estudio |
| DELETE | `/api/uploads/{upload_id}` | Descarta una ingesta |

Las descargas de estudios usan `ETag`, `Last-Modified` y `Cache-Control: no-cache`: el navegador puede
guardar el volumen y revalidarlo; si no cambió, la petición condicional recibe **304 sin cuerpo**.
No se usa `proxy_cache` en nginx. Que la API soporte 304 no garantiza que el navegador conserve todos
los volúmenes grandes; la limitación observada con T1Gd se registra en [PROGRESS, CP-034](docs/PROGRESS.md).
Contratos y extensiones en [`PLAN_MVP.md` §7, §13, §14 y §16](docs/PLAN_MVP.md).

### Variables de entorno

Prefijo `CERBERUS_`; los valores por defecto son relativos a la raíz del repo.

| Variable | Default |
|---|---|
| `CERBERUS_DATA_DIR` | `Data` |
| `CERBERUS_STORAGE_DIR` | `storage` |
| `CERBERUS_MODELS_DIR` | `models` |
| `CERBERUS_REDIS_URL` | `redis://localhost:6379` |
| `CERBERUS_MAX_UPLOAD_MB` | `2048` |
| `CERBERUS_MAX_ZIP_UNCOMPRESSED_MB` | `4096` |
| `CERBERUS_CORS_ORIGINS` | `["http://localhost:5173"]` (deriva de `CERBERUS_UI_PORT`) |
| `CERBERUS_CPU_THREADS` | `auto` (o entero positivo; se lee al arrancar el worker) |

El autoajuste también funciona en desarrollo. Si cambias `CERBERUS_CPU_THREADS`, reinicia el worker.
En Docker, las variables `*_PATH` de la tabla anterior seleccionan carpetas del host; `*_DIR` son
las rutas internas que Compose configura en `/app/`.

## Resultados de referencia (paciente 001/t0)

| Métrica | Valor |
|---|---|
| GTV (planimetría) | 33.14 cm³ |
| ABC/2 | 51.38 cm³ (+55 % vs planimetría) |
| MONAI WT / TC / ET | 53.51 / 31.01 / 20.99 cm³ |
| Dice vs GTV | TC 0.857 · WT 0.718 (rango inter-observador típico 0.72–0.88) |
| Tiempo de inferencia | ~13–18 s en Apple MPS |

## Desarrollo en equipo

El proyecto se desarrolla por tickets con trazabilidad entre dispositivos y agentes (Codex, Claude Code, etc.):

- [`AGENTS.md`](AGENTS.md) — reglas para cualquier agente o colaborador.
- [`docs/PLAN_MVP.md`](docs/PLAN_MVP.md) — alcance, arquitectura, contratos de API y tickets.
- [`docs/TRAINING.md`](docs/TRAINING.md) — pipeline de fine-tuning (CLI `cerberus_training`): manual de uso y smoke sintético (`uv run python -m cerberus_training smoke --synthetic`). Aún no se ha hecho ningún entrenamiento real.
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — checkpoints; sigue el protocolo de §12 del plan (reclamar ticket, registrar CP al terminar).
- [`docs/HANDOFF.md`](docs/HANDOFF.md) — estado actual, trabajo en curso y siguiente paso.
- [`docs/QA_UX_UI.md`](docs/QA_UX_UI.md) — evidencia histórica del QA visual y sus límites.
- [`docs/QA_2026-10-29.md`](docs/QA_2026-10-29.md) — fallos conocidos y plan de corrección pendiente.
- [`tools/e2e/README.md`](tools/e2e/README.md) — requisitos y comandos para QA de desarrollo y smoke Docker.

Checks obligatorios antes de un PR:

```bash
uv run ruff check backend && uv run ruff format --check backend && uv run pyright && uv run pytest -m "not slow"
cd frontend && npm run build                               # tsc -b && vite build
```

Los tests lentos (`uv run pytest -m slow`) requieren `Data/001` (Git LFS) y los pesos MONAI en `models/`.

## Datos

El repositorio solo incluye al **paciente 001** como muestra (~770 MB vía Git LFS) para no exceder la cuota de LFS.
Para el resto de pacientes (002–005, varios tiempos), descarga la colección **CFB-GBM** desde
[TCIA](https://www.cancerimagingarchive.net/) y colócala en `Data/` respetando la estructura de arriba.
El notebook detecta automáticamente todo lo que haya en `Data/*/t*/*.nii.gz`.

## Privacidad y limitaciones conocidas

**La ingesta actual no garantiza anonimización completa.** El QA reprodujo que dcm2niix conserva
`ImageComments` en `aux_file` del NIfTI y la hora de adquisición en `descrip`; también detectó nombres de
archivos en errores y conservación de metadatos en NIfTI subidos. El aviso de anonimización del formulario
todavía no refleja estos hallazgos. Usa datos previamente anonimizados y revisa también las cabeceras,
los nombres de archivo y el texto identificable «quemado» en los píxeles.

La limpieza de DICOM crudo se intenta en un `finally`, pero un crash o ciertos casos de cancelación
pueden dejar archivos temporales. A2 ofrece login y sesiones, pero los recursos aún requieren la protección
de A3. El QA registra además CSRF, DNS rebinding
y subidas NIfTI capaces de agotar la memoria. Estas correcciones siguen pendientes; el detalle,
las reproducciones y las prioridades están en [`QA_2026-10-29.md`](docs/QA_2026-10-29.md).

Uso de los datos sujeto a la licencia y política de citación de TCIA para la colección CFB-GBM.
