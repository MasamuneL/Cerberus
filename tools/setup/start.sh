#!/usr/bin/env bash
# Inicio local del paquete. Python se ejecuta únicamente dentro de la imagen de aplicación.
set -euo pipefail
root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
cd "$root"
lock="$root/.cerberus-setup.lock"
locked=false
command_pid=''
watch_pid=''
cleanup() {
    if [ -n "$command_pid" ]; then
        kill "$command_pid" 2>/dev/null || true
        kill -KILL "$command_pid" 2>/dev/null || true
        wait "$command_pid" 2>/dev/null || true
    fi
    if [ -n "$watch_pid" ]; then kill "$watch_pid" 2>/dev/null || true; fi
    if [ "$locked" = true ]; then rmdir "$lock" 2>/dev/null || true; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
bounded() {
    local seconds=$1 status=0 elapsed=0
    shift
    "$@" & command_pid=$!
    (
        while kill -0 "$command_pid" 2>/dev/null; do
            sleep 1
            elapsed=$((elapsed + 1))
            if [ "$elapsed" -ge "$seconds" ]; then
                kill "$command_pid" 2>/dev/null || true
                sleep 2
                kill -KILL "$command_pid" 2>/dev/null || true
                exit
            fi
        done
    ) >/dev/null 2>&1 & watch_pid=$!
    wait "$command_pid" || status=$?
    command_pid=''
    kill "$watch_pid" 2>/dev/null || true
    wait "$watch_pid" 2>/dev/null || true
    watch_pid=''
    return "$status"
}
no_browser=${CERBERUS_NO_BROWSER:-0}
case "${1:-}" in '') ;; --no-browser) no_browser=1 ;; *) fail 'Opción válida: --no-browser' ;; esac
command -v docker >/dev/null || fail 'Instala Docker Desktop o Docker Engine con plugin Compose y vuelve a iniciar.'
command -v curl >/dev/null || fail 'Falta curl. Instálalo con el gestor de tu sistema o usa docker compose up -d --wait.'
[ -f release.json ] || fail 'Esta entrada requiere un paquete de distribución con release.json; para desarrollar usa Compose con --build.'
mkdir "$lock" 2>/dev/null || fail 'Otra operación usa esta instalación (.cerberus-setup.lock). Si fue interrumpida, comprueba que terminó antes de retirar el lock vacío.'
locked=true

# Solo se leen cuatro valores públicos. Nunca source, eval ni expansión de comandos del archivo.
file_http='' file_identity='' file_project='' file_origin=''
if [ -f .env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line=${line%$'\r'}
        case "$line" in ''|'#'*) continue ;; esac
        key=${line%%=*}; value=${line#*=}
        case "$value" in \"*\") value=${value:1:${#value}-2} ;; \'*\') value=${value:1:${#value}-2} ;; esac
        case "$key" in
            CERBERUS_HTTP_PORT) file_http=$value ;;
            CERBERUS_KEYCLOAK_HTTP_PORT) file_identity=$value ;;
            COMPOSE_PROJECT_NAME) file_project=$value ;;
            CERBERUS_APP_ORIGIN) file_origin=$value ;;
        esac
    done < .env
fi
http=${CERBERUS_HTTP_PORT:-${file_http:-8080}}
identity=${CERBERUS_KEYCLOAK_HTTP_PORT:-${file_identity:-8081}}
project=${COMPOSE_PROJECT_NAME:-${file_project:-cerberus}}
origin=${CERBERUS_APP_ORIGIN:-$file_origin}
auto_http=false; auto_identity=false
[ -n "${CERBERUS_HTTP_PORT:-}$file_http" ] || auto_http=true
[ -n "${CERBERUS_KEYCLOAK_HTTP_PORT:-}$file_identity" ] || auto_identity=true
custom_origin=$origin
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || fail 'COMPOSE_PROJECT_NAME inválido.'
for port in "$http" "$identity"; do
    [[ "$port" =~ ^[0-9]{1,5}$ ]] && [ "$port" -ge 1 ] && [ "$port" -le 65535 ] || fail 'Los puertos deben ser enteros entre 1 y 65535.'
done
http=$((10#$http)); identity=$((10#$identity))
version=$(docker compose version --short) || fail 'No está disponible Docker Compose. Instala el plugin 2.30.0 o posterior.'
version=${version#v}
IFS=. read -r major minor patch <<< "$version"
[[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || fail 'No se pudo identificar la versión de Compose.'
if [ "$major" -lt 2 ] || { [ "$major" -eq 2 ] && [ "$minor" -lt 30 ]; }; then fail 'Se requiere Compose 2.30.0 o posterior.'; fi
printf 'Etapa 1/4: comprobar Docker, contexto y plataforma.\n'
info=$(docker info --format '{{.OSType}}|{{.Architecture}}|{{.NCPU}}|{{.MemTotal}}') || fail 'Docker no responde. Arranca el daemon o Docker Desktop.'
IFS='|' read -r os architecture cpus memory <<< "$info"
[ "$os" = linux ] || fail 'Selecciona contenedores Linux en Docker Desktop.'
case "$architecture" in amd64|x86_64) ;; arm64|aarch64) printf 'Backend Linux amd64: se comprobará la emulación del entorno Docker.\n' ;; *) fail 'Arquitectura Docker no compatible con Linux amd64.' ;; esac
if [ -n "${DOCKER_CONTEXT:-}" ]; then
    endpoint=$(docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')
else
    endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')}
fi
case "$endpoint" in unix://*|npipe://*) ;; *) fail 'Usa un contexto Docker local: los puertos de esta demo se publican en loopback del host Docker.' ;; esac
printf 'Docker: %s CPU; %s bytes de RAM total. Disco disponible: se comprobará dentro de la imagen.\n' "$cpus" "$memory"
export COMPOSE_PROJECT_NAME=$project
compose=(docker compose --project-directory "$root" -f "$root/compose.yaml" -p "$project")
existing=$(docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.ID}}') || fail 'No se pudo comprobar la instalación existente.'
# Un proyecto detenido conserva sus volúmenes e identidad; tampoco se adopta desde otra carpeta.
for container in $existing; do
    directory=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container") || fail 'No se pudo identificar la carpeta del proyecto existente.'
    [ "$directory" = "$root" ] || fail 'Ya existe una instancia de este proyecto en otra carpeta. Usa su instalación original; no se modificó.'
done
active=$(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.ID}}') || fail 'No se pudo comprobar la instancia activa.'
if [ -z "$active" ]; then
    occupied() { (exec 3<>"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1; }
    choose_port() {
        local candidate=$1 reserved=$2 tries=0
        while occupied "$candidate" || [ "$candidate" = "$reserved" ]; do
            candidate=$((candidate + 1)); tries=$((tries + 1))
            [ "$tries" -lt 100 ] && [ "$candidate" -le 65535 ] || return 1
        done
        printf '%s' "$candidate"
    }
    if occupied "$http"; then
        [ -z "${CERBERUS_HTTP_PORT:-}$file_http" ] || fail 'CERBERUS_HTTP_PORT está ocupado; conserva el servicio ajeno y elige otro puerto explícito.'
        http=$(choose_port 8080 "$identity") || fail 'No se encontró un puerto HTTP libre en 100 intentos.'
    fi
    if occupied "$identity" || [ "$identity" = "$http" ]; then
        [ -z "${CERBERUS_KEYCLOAK_HTTP_PORT:-}$file_identity" ] || fail 'CERBERUS_KEYCLOAK_HTTP_PORT está ocupado o coincide con HTTP; elige otro puerto explícito.'
        identity=$(choose_port 8081 "$http") || fail 'No se encontró un puerto de identidad libre en 100 intentos.'
    fi
fi
origin=${origin:-http://localhost:$http}
[[ "$origin" =~ ^http://(localhost|127\.0\.0\.1):$http$ ]] || fail 'CERBERUS_APP_ORIGIN debe ser un origen HTTP de loopback con el puerto HTTP seleccionado.'
export CERBERUS_HTTP_PORT=$http CERBERUS_KEYCLOAK_HTTP_PORT=$identity CERBERUS_APP_ORIGIN=$origin
issuer="http://localhost:$identity/realms/cerberus"
# La configuración guardada puede haber cambiado desde el último arranque.
# Se compara con los contenedores antes de escribir .env o recrear servicios.
for container in $active; do
    service=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.service" }}' "$container") || fail 'No se pudo identificar el servicio activo.'
    case "$service" in
        frontend|keycloak)
            expected=$http
            [ "$service" != keycloak ] || expected=$identity
            binding=$(docker port "$container" 8080/tcp) || fail 'No se pudo comprobar el puerto de la instancia activa.'
            [ "$binding" = "127.0.0.1:$expected" ] || fail 'Los puertos difieren de la instancia activa. Detén primero su instalación antes de cambiarlos.'
            ;;
        api)
            docker exec "$container" python -c 'import os,sys; assert os.environ.get("CERBERUS_APP_ORIGIN")==sys.argv[1] and os.environ.get("CERBERUS_OIDC_ISSUER_URL")==sys.argv[2]' "$origin" "$issuer" || fail 'Origen o issuer difiere de la instancia activa. Detén primero su instalación antes de cambiarlos.'
            ;;
    esac
done
timeout=${CERBERUS_START_TIMEOUT_SECONDS:-600}
pull_timeout=${CERBERUS_PULL_TIMEOUT_SECONDS:-1800}
for seconds in "$timeout" "$pull_timeout"; do [[ "$seconds" =~ ^[1-9][0-9]{0,4}$ ]] || fail 'Los tiempos de espera deben ser segundos enteros positivos.'; done

# Escritura atómica; se conservan otras claves, comentarios y rutas de la instalación.
persist_configuration() {
    local temporary line
    temporary=$(mktemp "$root/.env.setup.XXXXXX")
    if [ -f .env ]; then
        while IFS= read -r line || [ -n "$line" ]; do
            line=${line%$'\r'}
            case "$line" in CERBERUS_HTTP_PORT=*|CERBERUS_KEYCLOAK_HTTP_PORT=*|COMPOSE_PROJECT_NAME=*|CERBERUS_APP_ORIGIN=*) ;; *) printf '%s\n' "$line" >> "$temporary" ;; esac
        done < .env
    fi
    printf 'COMPOSE_PROJECT_NAME=%s\nCERBERUS_HTTP_PORT=%s\nCERBERUS_KEYCLOAK_HTTP_PORT=%s\nCERBERUS_APP_ORIGIN=%s\n' "$project" "$http" "$identity" "$origin" >> "$temporary"
    mv "$temporary" .env
}
persist_configuration
printf 'Etapa 2/4: descargar imágenes fijadas a esta versión.\n'
images=$("${compose[@]}" config --images) || fail 'No se pudieron resolver las imágenes del paquete.'
[ -n "$images" ] || fail 'El paquete no declara imágenes.'
all_cached=true
while IFS= read -r image; do
    [[ "$image" =~ @sha256:[a-f0-9]{64}$ ]] || fail 'Todas las imágenes del paquete deben estar fijadas por digest.'
    docker image inspect "$image" >/dev/null 2>&1 || all_cached=false
done <<< "$images"
if [ "$all_cached" = true ]; then
    printf 'Todas las imágenes por digest están en caché; no se requiere descarga.\n'
elif ! bounded "$pull_timeout" "${compose[@]}" pull; then
    fail 'La descarga falló o agotó su espera. Reintenta: los datos y volúmenes se conservaron.'
fi
backend=$("${compose[@]}" config --images api) || fail 'No se pudo resolver la imagen backend.'
[[ "$backend" =~ @sha256:[a-f0-9]{64}$ ]] || fail 'El paquete requiere una imagen backend fijada por digest.'
docker run --rm --network none --platform linux/amd64 --entrypoint python "$backend" -c 'import shutil; d=shutil.disk_usage("/"); print("Disco del entorno Docker: %d bytes libres, %d bytes totales." % (d.free,d.total))' || fail 'No se pudo ejecutar Linux amd64 o medir el disco Docker. Revisa emulación y espacio.'
for component in api frontend; do
    image=$("${compose[@]}" config --images "$component")
    labels=$(docker image inspect --format '{{json .Config.Labels}}' "$image") || fail 'No se pudieron inspeccionar las imágenes descargadas.'
    printf '%s' "$labels" | docker run --rm -i --network none --platform linux/amd64 --entrypoint python \
        --mount "type=bind,src=$root/release.json,dst=/release.json,readonly" "$backend" -c 'import json,sys; m=json.load(open("/release.json")); l=json.load(sys.stdin); assert m["format"]==1 and m["images"][sys.argv[1]]==sys.argv[2] and l.get("org.opencontainers.image.revision")==m["revision"] and l.get("org.opencontainers.image.version")==m["version"], "La imagen no coincide con release.json"' "$(if [ "$component" = api ]; then printf backend; else printf frontend; fi)" "$image" || fail 'Las imágenes mezclan versiones o no coinciden con release.json.'
done
# Una descarga larga puede perder la reserva. Reintento acotado, solo para valores automáticos.
if [ -z "$active" ]; then
    for attempt in 1 2; do
        changed=false
        if occupied "$http"; then
            [ "$auto_http" = true ] && [ -z "$custom_origin" ] || fail 'El puerto HTTP se ocupó durante la descarga. Elige otro puerto antes de reintentar.'
            http=$(choose_port "$((http + 1))" "$identity") || fail 'No se encontró otro puerto HTTP libre.'
            changed=true
        fi
        if occupied "$identity"; then
            [ "$auto_identity" = true ] || fail 'El puerto de identidad se ocupó durante la descarga. Elige otro puerto antes de reintentar.'
            identity=$(choose_port "$((identity + 1))" "$http") || fail 'No se encontró otro puerto de identidad libre.'
            changed=true
        fi
        [ "$changed" = true ] || break
        origin=${custom_origin:-http://localhost:$http}
        issuer="http://localhost:$identity/realms/cerberus"
        export CERBERUS_HTTP_PORT=$http CERBERUS_KEYCLOAK_HTTP_PORT=$identity CERBERUS_APP_ORIGIN=$origin
        persist_configuration
    done
fi
printf 'Etapa 3/4: preparar datos, identidad y aplicación; espera máxima %s s.\n' "$timeout"
if ! bounded "$((timeout + 30))" "${compose[@]}" up -d --pull never --wait --wait-timeout "$timeout"; then
    printf 'El arranque no terminó. Los inicializadores con salida 0 son normales.\n' >&2
    if [ -f "$root/tools/setup/diagnose.sh" ]; then bash "$root/tools/setup/diagnose.sh" || true; fi
    fail 'Revisa el diagnóstico y vuelve a iniciar. No se borraron volúmenes ni datos.'
fi
printf 'Etapa 4/4: comprobar nginx, API y proveedor OIDC.\n'
http_get() { curl --fail --silent --show-error --max-time 15 --noproxy '*' "$1"; }
[ "$(http_get "$origin/healthz")" = ok ] || fail 'La respuesta HTTP no corresponde al frontend de Cerberus.'
health=$(http_get "$origin/api/health") || fail 'La API no responde por el proxy.'
auth=$(http_get "$origin/api/auth/config") || fail 'No se pudo comprobar la autenticación.'
discovery=$(http_get "$issuer/.well-known/openid-configuration") || fail 'El proveedor OIDC no está listo en su URL pública.'
printf '%s\0%s\0%s' "$health" "$auth" "$discovery" | "${compose[@]}" exec -T api python -c 'import json,os,sys; h,a,d=map(json.loads,sys.stdin.read().split("\0")); assert h=={"status":"ok"} and a=={"mode":"oidc"}; assert d["issuer"]==sys.argv[2]; assert os.environ["CERBERUS_APP_ORIGIN"]==sys.argv[1] and os.environ["CERBERUS_OIDC_ISSUER_URL"]==sys.argv[2], "Origen o issuer incoherente"' "$origin" "$issuer" || fail 'La respuesta pública, origen o issuer no coincide con la instalación.'
login_headers=$(curl --silent --show-error --max-time 15 --noproxy '*' --dump-header - --output /dev/null "$origin/api/auth/login") || fail 'No se pudo iniciar el flujo de login público.'
printf '%s' "$login_headers" | "${compose[@]}" exec -T api python -c 'import email,sys,urllib.parse; raw=sys.stdin.read(); status,headers=raw.split("\n",1); h=email.message_from_string(headers); u=urllib.parse.urlsplit(h.get("Location","")); q=urllib.parse.parse_qs(u.query); assert " 302 " in status; assert urllib.parse.urlunsplit((u.scheme,u.netloc,u.path,"",""))==sys.argv[2]+"/protocol/openid-connect/auth" and q.get("redirect_uri")==[sys.argv[1]+"/api/auth/callback"] and q.get("client_id")==["cerberus-web"], "Callback o proveedor de login incorrecto"' "$origin" "$issuer" || fail 'El login público no corresponde al origen y callback de esta instalación.'
printf 'Cerberus listo: %s\nCuenta local: demo / demo\n' "$origin"
if [ "$no_browser" != 1 ]; then
    if command -v open >/dev/null; then open "$origin" || true
    elif command -v xdg-open >/dev/null; then xdg-open "$origin" >/dev/null 2>&1 || true
    else printf 'Abre manualmente la URL anterior en tu navegador.\n'; fi
fi
