# Cerberus

Análisis exploratorio, visualización 3D y segmentación de glioblastoma sobre el dataset **CFB-GBM** (The Cancer Imaging Archive).

Además del notebook, Cerberus es ahora una **app web**: backend **FastAPI + arq/Redis + MONAI** y frontend
**React + Vite + TypeScript + [Niivue](https://github.com/niivue/niivue)** como visor de imagen médica.

Proyecto de Big Data — UDG, 5.º semestre.

La app ya integra el MVP, áreas de Brodmann y dominios funcionales, mejoras de UX/UI, Docker Compose,
autoajuste de recursos y caché HTTP de volúmenes. Estado y trabajo pendiente en
[`docs/HANDOFF.md`](docs/HANDOFF.md); historial en [`docs/PROGRESS.md`](docs/PROGRESS.md).
Los hallazgos del [QA de seguridad y robustez](docs/QA_2026-10-29.md) siguen pendientes de corrección.

**Autenticación en desarrollo:** A0 incorpora configuración validada y contratos para OIDC, sesiones y roles
lector/analista. A1 añade Keycloak persistente y A2 login/sesiones en la API. La protección de recursos
todavía requiere A3, y la interfaz de acceso A4; `CERBERUS_AUTH_MODE=oidc` por sí solo aún no protege el catálogo.
El modo local conserva `off` por defecto.
Variables, restricciones y tickets en
[`PLAN_MVP.md` §17](docs/PLAN_MVP.md#17-autenticación-para-demo-académica--oidc--keycloak).

## Qué incluye

- **`cerberus_eda.py`** — notebook [marimo](https://marimo.io) con:
  - Inventario de la data (secuencias, shape, spacing, dtype).
  - Cortes axial / coronal / sagital sincronizados con máscara GTV superpuesta.
  - Volumetría tumoral (planimetría vs ABC/2, umbrales RANO 2.0).
  - Líneas base clásicas de segmentación (Otsu, K-Means).
  - Segmentación con **MONAI Model Zoo `brats_mri_segmentation`** (SegResNet).
  - Iso-superficies 3D con **Mayavi** (offscreen) y Plotly interactivo.
- **`cerberus_mayavi.py`** — escena Mayavi reutilizable; también abre una ventana Qt interactiva a partir de un `.npz` exportado por el notebook.

> ⚠️ La máscara de referencia del dataset es el **GTV de radioterapia** (puede incluir cavidad de resección y excluye edema), no el "volumen tumoral" genérico.

## Estructura

```
Cerberus/
├── cerberus_eda.py        # notebook marimo principal
├── cerberus_mayavi.py     # escena 3D Mayavi
├── backend/
│   ├── cerberus_api/      # FastAPI (main, routers/, servicios, worker arq)
│   └── tests/             # pytest
├── frontend/              # React + Vite + TS + Niivue
├── docs/
│   ├── PLAN_MVP.md        # plan, contratos y tickets del MVP
│   ├── PROGRESS.md        # bitácora de checkpoints
│   ├── HANDOFF.md         # estado actual y cómo continuar
│   ├── QA_UX_UI.md        # evidencia y límites del QA visual
│   └── QA_2026-10-29.md   # hallazgos pendientes de seguridad y robustez
├── compose.yaml           # redis, api, worker y frontend
├── docker/                # Dockerfiles y configuración nginx
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

## Uso

```bash
# Editar / explorar el notebook
uv run marimo edit cerberus_eda.py

# Modo app (solo lectura)
uv run marimo run cerberus_eda.py

# Ventana Mayavi interactiva con una escena exportada desde el notebook
uv run python cerberus_mayavi.py escena.npz
```

La primera ejecución de la celda MONAI descarga el bundle `brats_mri_segmentation` en `models/`.

## App web

### Qué puerto abrir

| Cómo arrancaste la app | URL de la UI | Servidor que la entrega |
|---|---|---|
| `docker compose up -d --build` | **http://localhost:8080** | nginx, con el frontend compilado por Vite |
| `cd frontend && npm run dev` | **http://localhost:5173** por defecto | servidor de desarrollo de Vite |

Es el mismo frontend React en ambos modos. **Docker no inicia el servidor de desarrollo en 5173**:
si solo levantaste Compose, abre **8080**. El puerto de Docker se puede cambiar con `CERBERUS_HTTP_PORT`.
En desarrollo, Vite necesita seguir ejecutándose en una terminal; la API se inicia aparte en **8000**.
Con Compose, nginx reenvía `/api` al puerto 8000 interno del contenedor, que no se publica en el host.

### Opción rápida: Docker Desktop (recomendada para usarla)

Requisitos: [Docker Desktop](https://www.docker.com/products/docker-desktop/) con **≥ 8 GB de RAM** asignados
(Settings → Resources) y la muestra `Data/001` descargada con Git LFS. En Mac con Apple Silicon activa
*Use Rosetta for x86_64/amd64 emulation* (Settings → General): el backend es `linux/amd64` porque ANTs no publica
wheel ARM para Linux.

```bash
docker compose up -d --build      # primer build: varios minutos (torch CPU + ANTs)
docker compose ps                 # redis, api, worker y frontend deben estar "healthy"
open http://localhost:8080        # la app
docker compose logs -f worker     # ver jobs de segmentación / áreas
docker compose down               # parar (añade -v para borrar también la cola de Redis)
```

En Docker Desktop aparece el proyecto **cerberus** con 4 contenedores. Solo se publica `127.0.0.1:8080` (nginx):
`/api` se reenvía a la API y Redis queda en la red interna. `Data/`, `storage/` y `models/` se montan desde el repo,
así que los resultados se comparten con el modo de desarrollo.

| Variable (opcional) | Default | Para qué |
|---|---|---|
| `CERBERUS_HTTP_PORT` | 8080 | puerto local de la app |
| `CERBERUS_CPU_THREADS` | auto | hilos de MONAI/ANTs; `auto` = máx(1, mín(floor(CPUs) − 1, 8)) según las CPU disponibles; un entero positivo lo fija (ver `GET /api/system`) |
| `CERBERUS_WORKER_MEM_LIMIT` / `CERBERUS_API_MEM_LIMIT` | 6g / 2g | límites de memoria |
| `CERBERUS_DATA_PATH` / `CERBERUS_MODELS_PATH` | `./Data` / `./models` | carpetas del host para datos y modelos |
| `CERBERUS_STORAGE_PATH` | `./storage` | separar los resultados de Docker de los de desarrollo |
| `CERBERUS_UID` / `CERBERUS_GID` | 1000 | solo en Linux: `$(id -u)` / `$(id -g)` |

**Rendimiento** (Mac de 14 CPU, Docker con CPU bajo Rosetta, 4 hilos): segmentación MONAI ~2 min (92 s con 8 hilos;
en desarrollo con MPS ~18 s), mapeo de áreas ~1.5 min en frío y ~30 s con el registro en caché. Pico del worker
~4.2 GiB. La segmentación de referencia coincide con la de desarrollo (001/t0: Dice TC 0.857);
el registro ANTs puede variar entre ejecuciones con varios hilos. Son mediciones del 2026-10-29,
no tiempos garantizados para cualquier equipo o estudio.

Smoke test de la versión Docker: `cd tools/e2e && npm ci && CERBERUS_UI=http://localhost:8080 node verify-docker.mjs`.

### Identidad y sesiones de la demo (A1/A2)

El overlay añade **Keycloak 26.8.1 en http://localhost:8081** y PostgreSQL 18 privado. Cerberus conserva
**http://localhost:8080**. A2 añade las rutas de login, sesión y logout; los permisos de recursos todavía
se completan en A3 y la UI de acceso en A4. El overlay en esta etapa no protege el catálogo ni los archivos.

```bash
uv run python tools/auth/bootstrap.py
docker compose --env-file .env.auth -f compose.yaml -f compose.auth.yaml up -d --build
docker compose --env-file .env.auth -f compose.yaml -f compose.auth.yaml ps
```

El bootstrap crea `.env.auth` con permisos `0600` y tres secretos aleatorios distintos; no los imprime
ni sobrescribe un archivo existente. Si se proporcionan `CERBERUS_AUTH_DB_PASSWORD`,
`CERBERUS_KEYCLOAK_ADMIN_PASSWORD` o `CERBERUS_OIDC_CLIENT_SECRET` en el entorno, los usa al crear el archivo.
Este generador exige al menos 32 caracteres URL-safe (letras, números, `_` y `-`), evitando interpolación
accidental de Compose. `.env.auth` está ignorado por Git. Conserva el archivo para los siguientes arranques:
cambiar su contraseña de base de datos no cambia automáticamente la de un volumen existente.

En http://localhost:8081/admin, entra como `cerberus-admin` con la contraseña administrativa del archivo
local. Selecciona el realm **cerberus**, crea las cuentas desde **Users** y asigna en **Role mapping** uno
de los roles del cliente **cerberus-web**: `reader` o `analyst`. El realm no incluye cuentas ni contraseñas,
el registro público está desactivado y los roles administrativos de Keycloak no conceden permisos de Cerberus.
Los usuarios creados conservan sus contraseñas al repetir el bootstrap o reiniciar servicios.

El cliente exige Authorization Code con PKCE S256 y registra exactamente
`http://localhost:8080/api/auth/callback`. El claim `cerberus_roles` del ID Token contiene únicamente roles
de `cerberus-web`. El password grant, el flujo implícito y las cuentas de servicio del cliente están desactivados.
En desarrollo, **5173** sigue siendo Vite y **8000** la API nativa; para registrar el callback de Vite en una
instalación nueva usa `CERBERUS_APP_ORIGIN=http://localhost:5173` al ejecutar el overlay. La importación de
un realm existente se omite para conservar sus cuentas: los cambios posteriores de redirect URIs se hacen
explícitamente desde la consola, sin recrear el realm.

| Variable del overlay | Default |
|---|---|
| `CERBERUS_KEYCLOAK_HTTP_PORT` | `8081`, solo loopback |
| `CERBERUS_KEYCLOAK_ADMIN_USERNAME` | `cerberus-admin` |
| `CERBERUS_APP_ORIGIN` | `http://localhost:8080` |
| Issuer público | `http://localhost:8081/realms/cerberus` |
| Backchannel de API en Docker | `http://keycloak:8080/realms/cerberus` |

La metadata conserva el issuer público y ofrece token/JWKS por la red interna; no se desactivan las
validaciones OIDC. PostgreSQL no publica puertos y solo comparte su red privada con Keycloak. Los datos
de identidad viven en volúmenes `auth-db-data` y `keycloak-data`; el catálogo y las imágenes siguen en disco.
Para parar, usa el mismo comando de Compose con ambos archivos y `down`, sin `-v` si quieres conservar
las cuentas. `start-dev` y HTTP pertenecen exclusivamente a esta demo local.

Con el overlay activo, puedes iniciar sesión en **http://localhost:8080/api/auth/login**. FastAPI usa
Authorization Code + PKCE S256 con Authlib y verifica firma RS256, issuer, audience, expiración, nonce
y `azp` antes de crear la sesión. Una cuenta sin roles de Cerberus recibe 403. El navegador conserva
solo una cookie opaca `HttpOnly`/`SameSite=Lax`, sin tokens OIDC en almacenamiento del navegador.

`GET /api/auth/me` devuelve roles, vencimiento efectivo y token CSRF. `POST /api/auth/logout` requiere
`Origin` de la app y ese token en `X-CSRF-Token`: invalida Redis y borra cookies; cierra la sesión de
Cerberus, no la de otras aplicaciones del proveedor. La inactividad caduca a 30 minutos y la duración
absoluta a 60; el overlay admite `CERBERUS_AUTH_IDLE_TIMEOUT_SECONDS` y
`CERBERUS_AUTH_ABSOLUTE_TIMEOUT_SECONDS` para configurarlas. Redis caído produce 503; Keycloak caído
impide nuevos logins, mientras las sesiones válidas continúan hasta vencer. Respuestas de auth: `no-store`.
En modo local `off`, `/api/auth/config` informa el modo y las otras rutas de auth devuelven 404.

### Modo desarrollo: requisitos

- Python 3.11 + [uv](https://docs.astral.sh/uv/)
- Node `^20.19.0 || >=22.12.0` (según Vite en `frontend/package-lock.json`) y npm
- Redis (`brew install redis`)
- [Git LFS](https://git-lfs.com) (para la muestra en `Data/001`)

### Arranque (4 terminales, desde la raíz)

```bash
uv sync                                                    # una vez: deps Python
redis-server                                               # terminal 1
uv run arq cerberus_api.worker.WorkerSettings              # terminal 2: worker
uv run uvicorn cerberus_api.main:app --reload --reload-dir backend --port 8000  # terminal 3: API
cd frontend && npm install && npm run dev                  # terminal 4: UI
```

- UI de desarrollo (con Vite ejecutándose): <http://localhost:5173>. Si usas Docker: <http://localhost:8080>.
- Documentación interactiva de la API: <http://localhost:8000/docs>
- Si el puerto 5173 está ocupado: `cd frontend && npx vite --port 5180 --strictPort`
  (agrega ese origen a `CERBERUS_CORS_ORIGINS` si llamas a la API sin el proxy de Vite).

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
| `CERBERUS_CORS_ORIGINS` | `["http://localhost:5173"]` |
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
