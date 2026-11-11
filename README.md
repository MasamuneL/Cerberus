# Cerberus

## Usar la demo

**D3 en implementación; todavía sin paquete publicado ni matriz de plataformas aprobada.**
El paquete previsto requiere Docker: descargar, descomprimir, iniciar y entrar con `demo` / `demo`.
[Guía de instalación, datos, diagnóstico y actualización](docs/INSTALL.md).
Mientras se valida D3, siguen disponibles los comandos Compose del checkout descritos abajo.

## Desarrollar

El desarrollo utiliza Git/LFS, uv y Node; las instrucciones y comandos existentes siguen vigentes.

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

La instalación normal incluye la app web. Para el notebook histórico se habilita el grupo opcional
`notebook`; los comandos y las rutas figuran en [`docs/ARCHIVO.md`](docs/ARCHIVO.md).

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

### Cómo se estiman las áreas de Brodmann

Cerberus adapta un atlas anatómico al espacio de cada paciente mediante **registro de imágenes**.
Este proceso es independiente de MONAI: SegResNet segmenta regiones de lesión; el registro ubica
las etiquetas del atlas sobre la RM. Las áreas y funciones mostradas son estimaciones educativas.

| Herramienta | Función |
|---|---|
| Nilearn | Obtiene el atlas Talairach-Brodmann, nivel `ba`, y la plantilla MNI152 con su máscara cerebral |
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
4. Aplica las transformaciones inversas al atlas previamente separado por hemisferios, con interpolación
   `genericLabel` para conservar etiquetas discretas. Guarda `brodmann.nii.gz` con el grid y affine de la
   secuencia de referencia del visor, preferentemente `t1gd`. Las transformaciones se reutilizan
   cuando las entradas y parámetros no cambian. Se presupone que las series están corregistradas.

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

**Limitación de coordenadas pendiente de resolver:** el código registra al paciente contra **MNI152**,
pero Nilearn identifica el atlas descargado como espacio **Talairach** (`template="Talairach"`).
Actualmente se aplica la inversa del registro MNI152 directamente al atlas, sin una conversión explícita
Talairach–MNI152. La suposición de que ambos espacios coinciden necesita corregirse o verificarse;
puede introducir errores de localización y debe resolverse antes de atribuir precisión anatómica al mapa.
Esta sección documenta el hallazgo; no implica que la conversión ya esté implementada.

La ausencia de `brain_mask`, disponer solo de T1 con contraste y un GTV grande pueden reducir la calidad
del registro. Un mapa alineado visualmente no demuestra localización funcional individual ni sustituye
fMRI, tractografía o mapeo cortical intraoperatorio.

Implementación: [`atlas.py`](backend/cerberus_api/atlas.py) y [`areas.py`](backend/cerberus_api/areas.py).
Referencias: [registro y transformaciones ANTsPy](https://antspy.readthedocs.io/en/latest/registration.html),
[atlas Talairach de Nilearn](https://nilearn.github.io/stable/modules/generated/nilearn.datasets.fetch_atlas_talairach.html)
y [definición del espacio en el código de Nilearn](https://github.com/nilearn/nilearn/blob/main/nilearn/datasets/atlas.py).

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
