#!/usr/bin/env bash
# Actualización explícita y recuperación en destinos nuevos. Nunca borra volúmenes.
set -Eeuo pipefail
umask 077

fail() { printf '%s\n' 'Operación detenida. Conserva datos y backups; consulta docs/D3_UPDATE.md.' >&2; exit 1; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
installation=$(CDPATH= cd -- "${CERBERUS_INSTALL_DIR:-"$script_dir/../.."}" && pwd -P)
mode=update
candidate=''
backup=''
paused=false
activated=false
lock=''
dump_created=false
volumes=(redis-data auth-db-data keycloak-data auth-db-secret keycloak-admin-secret oidc-client-secret)

compose() { docker compose --project-directory "$installation" -f "$installation/compose.yaml" -p "$project" "$@"; }
cleanup() {
  local status=$?
  trap - EXIT
  if [ "$dump_created" = true ]; then
    compose exec -T auth-db rm -f /tmp/cerberus-update.dump >/dev/null 2>&1 || true
  fi
  if [ "$status" -ne 0 ] && [ "$paused" = true ]; then
    if [ "$activated" = false ]; then
      compose up -d --no-build --pull never --wait --wait-timeout 180 >/dev/null 2>&1 || printf '%s\n' 'La instalación anterior sigue detenida; inicia desde su carpeta cuando resuelvas el fallo.' >&2
    else
      compose stop frontend api worker >/dev/null 2>&1 || true
      printf '%s\n' 'Aplicación detenida. Paquete previo y backup conservados; usa retorno explícito o restauración aislada.' >&2
    fi
  fi
  if [ -n "$lock" ]; then
    rm -f -- "$lock/labels.json"
    rmdir -- "$lock" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
case "${1:-}" in
  --backup) [ "$#" -eq 1 ] || fail; mode=backup ;;
  --rollback)
    [ "$#" -eq 2 ] && [[ "$2" =~ ^[a-f0-9]{40}$ ]] || fail
    candidate="$installation/.cerberus-versions/$2"
    ;;
  --restore)
    [ "$#" -eq 4 ] || fail
    mode=restore
    backup=$(CDPATH= cd -- "$2" && pwd -P) || fail
    destination=$3
    project=$4
    [[ "$project" =~ ^cerberus-(restore|qa)-[a-z0-9][a-z0-9_-]{0,49}$ ]] || fail
    mkdir -p -- "$destination" || fail
    destination=$(CDPATH= cd -- "$destination" && pwd -P)
    [ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ] || fail
    ;;
  '') fail ;;
  *) [ "$#" -eq 1 ] || fail; candidate=$(CDPATH= cd -- "$1" && pwd -P) || fail ;;
esac
cd -- "$installation"
command -v docker >/dev/null 2>&1 || fail
docker info >/dev/null 2>&1 || fail
# Docker remoto tiene otro sistema de archivos; nunca se envían mounts locales allí.
if [ -n "${DOCKER_CONTEXT:-}" ]; then
  endpoint=$(docker context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}') || fail
else
  endpoint=${DOCKER_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}')} || fail
fi
case "$endpoint" in unix://*|npipe://*) ;; *) fail ;; esac
if [ "$mode" != restore ]; then
  file_project=''
  if [ -f "$installation/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      line=${line%$'\r'}
      case "$line" in COMPOSE_PROJECT_NAME=*)
        value=${line#*=}
        case "$value" in \"*\") value=${value:1:${#value}-2} ;; \'*\') value=${value:1:${#value}-2} ;; esac
        file_project=$value ;;
      esac
    done < "$installation/.env"
  fi
  project=${COMPOSE_PROJECT_NAME:-${file_project:-cerberus}}
fi
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || fail
# Incluye contenedores detenidos: Compose también puede recrearlos.
existing=$(docker ps -a --filter "label=com.docker.compose.project=$project" --format '{{.ID}}') || fail
for container in $existing; do
  [ "$mode" != restore ] || fail
  directory=$(docker inspect --format '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$container") || fail
  directory=$(CDPATH= cd -- "$directory" && pwd -P) || fail
  [ "$directory" = "$installation" ] || fail
done
lock_root=$installation
[ "$mode" != restore ] || lock_root=$destination
mkdir -- "$lock_root/.cerberus-setup.lock" 2>/dev/null || fail
lock="$lock_root/.cerberus-setup.lock"

if [ "$mode" = restore ]; then
  # Verificación completa antes de crear volúmenes; el helper procede del backup privado.
  IFS= read -r helper < "$backup/helper-image.txt" || fail
  [[ "$helper" =~ ^[a-z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]] || fail
  docker image inspect "$helper" >/dev/null 2>&1 || fail
  docker run --rm --pull never --network none --platform linux/amd64 --user 0:0 --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL --cap-add DAC_OVERRIDE --entrypoint python \
    --volume "$backup:/backup:ro" "$helper" -m cerberus_api.release_state \
    --operation verify-backup --backup /backup >/dev/null 2>&1 || fail
  mounts=()
  for volume in "${volumes[@]}"; do
    docker volume inspect "${project}_${volume}" >/dev/null 2>&1 && fail
    mounts+=(--volume "${project}_${volume}:/run/cerberus-backup/$volume")
  done
  docker run --rm --pull never --network none --platform linux/amd64 --user 0:0 --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --entrypoint python --volume "$backup:/backup:ro" --volume "$destination:/restore" "${mounts[@]}" \
    "$helper" -m cerberus_api.release_state --operation restore --backup /backup \
    --destination /restore --project "$project" >/dev/null 2>&1 || fail
  printf '%s\n' 'Restauración preparada en proyecto nuevo, sin iniciar servicios. Revisa puertos y ejecuta su lanzador.'
  exit 0
fi

# Compose --images puede incluir dependencias; cada referencia sale del manifest.
manifest_image() {
  local image
  image=$(tr -d '\r\n' < "$1/release.json" | tr ',' '\n' | sed -nE 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p') || return 1
  [[ "$image" =~ ^[a-z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]] || return 1
  printf '%s' "$image"
}
helper=$(manifest_image "$installation" backend) || fail
[[ "$helper" =~ ^[a-z0-9./:_-]+@sha256:[a-f0-9]{64}$ ]] || fail
docker image inspect "$helper" >/dev/null 2>&1 || fail
if [ "$mode" = backup ]; then candidate=$installation; fi
[ "$candidate" != "$installation" ] || [ "$mode" = backup ] || fail

guard() {
  compose run --rm --no-deps --pull never -T --entrypoint python \
    --volume "$installation:/release/current:ro" --volume "$candidate:/release/candidate:ro" api \
    -m cerberus_api.release_state --current /release/current --candidate /release/candidate >/dev/null 2>&1
}
verify_images() {
  local package=$1 component image
  local records=()
  for component in backend frontend; do
    image=$(manifest_image "$package" "$component") || return 1
    template='{"version":{{json (index .Config.Labels "org.opencontainers.image.version")}},"revision":{{json (index .Config.Labels "org.opencontainers.image.revision")}},"architecture":{{json .Architecture}},"os":{{json .Os}}}'
    records+=("$(docker image inspect --format "$template" "$image" 2>/dev/null)") || return 1
  done
  printf '{"backend":%s,"frontend":%s}' "${records[0]}" "${records[1]}" > "$lock/labels.json"
  docker run --rm --pull never --network none --platform linux/amd64 --user 0:0 --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL --cap-add DAC_OVERRIDE --entrypoint python \
    --volume "$installation:/release/current:ro" --volume "$package:/release/candidate:ro" \
    --volume "$lock/labels.json:/release/labels.json:ro" "$helper" -m cerberus_api.release_state --operation verify-images \
    --current /release/current --candidate /release/candidate --labels /release/labels.json >/dev/null 2>&1
}
# El backend actual valida imágenes/configuración actuales antes de cualquier Compose run.
verify_images "$installation" || fail
# El backend actual valida ambos paquetes y la cola antes de descargar el candidato.
guard || fail
if [ "$mode" = update ]; then
  printf '%s\n' 'Descargando versión explícita; la instalación actual continúa disponible.'
  docker compose --project-directory "$installation" -f "$candidate/compose.yaml" -p "$project" pull >/dev/null 2>&1 || fail
  verify_images "$candidate" || fail
fi
printf '%s\n' 'Pausando aplicación y comprobando de nuevo la cola.'
paused=true
compose stop frontend api worker >/dev/null 2>&1 || fail
guard || fail
compose stop keycloak >/dev/null 2>&1 || fail
backup="$installation/.cerberus-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p -- "$backup" || fail
chmod 700 "$backup"
# Archivo binario: docker cp conserva bytes también en PowerShell 5.
compose exec -T auth-db sh -ec 'umask 077; test ! -e /tmp/cerberus-update.dump; trap "rm -f /tmp/cerberus-update.dump" EXIT; pg_dump -U keycloak -d keycloak -Fc -f /tmp/cerberus-update.dump; trap - EXIT' >/dev/null 2>&1 || fail
dump_created=true
database=$(compose ps -q auth-db 2>/dev/null) || fail
[[ "$database" =~ ^[a-f0-9]{12,64}$ ]] || fail
docker cp "$database:/tmp/cerberus-update.dump" "$backup/database.dump" >/dev/null 2>&1 || fail
compose exec -T auth-db rm /tmp/cerberus-update.dump >/dev/null 2>&1 || fail
dump_created=false
chmod 600 "$backup/database.dump"
compose exec -T redis redis-cli SAVE >/dev/null 2>&1 || fail
compose stop auth-db redis >/dev/null 2>&1 || fail

mounts=()
for specification in \
  'redis-data:redis:/data' 'auth-db-data:auth-db:/var/lib/postgresql' \
  'keycloak-data:keycloak:/opt/keycloak/data' 'auth-db-secret:auth-db:/run/cerberus/db' \
  'keycloak-admin-secret:keycloak:/run/cerberus/admin' 'oidc-client-secret:api:/run/cerberus/client'; do
  IFS=: read -r volume service target <<< "$specification"
  container=$(compose ps -aq "$service" 2>/dev/null) || fail
  [[ "$container" =~ ^[a-f0-9]{12,64}$ ]] || fail
  template='{{range .Mounts}}{{if eq .Destination "'"$target"'"}}{{.Name}}{{end}}{{end}}'
  physical=$(docker inspect --format "$template" "$container" 2>/dev/null) || fail
  [[ "$physical" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]+$ ]] || fail
  mounts+=(--volume "$physical:/run/cerberus-backup/$volume:ro")
done
printf '%s\n' 'Creando backup privado completo; puede ocupar tanto como datos y modelos existentes.'
api_container=$(compose ps -aq api 2>/dev/null) || fail
[[ "$api_container" =~ ^[a-f0-9]{12,64}$ ]] || fail
docker run --rm --pull never --network none --platform linux/amd64 --user 0:0 --read-only --tmpfs /tmp \
  --security-opt no-new-privileges:true --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --entrypoint python \
  --volumes-from "$api_container:ro" --volume "$installation:/release/current:ro" --volume "$backup:/backup" "${mounts[@]}" "$helper" \
  -m cerberus_api.release_state --operation backup --current /release/current --backup /backup \
  --helper-image "$helper" --quiesced >/dev/null 2>&1 || fail
if [ "$mode" = update ]; then
  activated=true
  docker run --rm --pull never --network none --platform linux/amd64 --user 0:0 --read-only --tmpfs /tmp \
    --security-opt no-new-privileges:true --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --entrypoint python \
    --volume "$installation:/release/current" --volume "$candidate:/release/candidate:ro" --volume "$backup:/backup:ro" \
    "$helper" -m cerberus_api.release_state --operation activate --current /release/current \
    --candidate /release/candidate --backup /backup --quiesced >/dev/null 2>&1 || fail
fi
compose up -d --no-build --pull never --wait --wait-timeout 240 >/dev/null 2>&1 || fail
paused=false
printf '%s\n' 'Operación completada. Backup privado en .cerberus-backups; paquete previo en .cerberus-versions.'
