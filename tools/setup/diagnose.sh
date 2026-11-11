#!/usr/bin/env bash
# Diagnóstico local: no muestra logs ni errores originales y no descarga imágenes.
set -u
docker_ready=false

partial() {
  if [ "$docker_ready" = true ]; then
    printf '%s\n' '{"format":1,"checks":[{"code":"DOCKER_READY","service":"docker","status":"ok","action":"Docker accesible en el contexto elegido."},{"code":"DIAGNOSTIC_UNAVAILABLE","service":"report","status":"pending","action":"Conserva la instalación; el diagnóstico completo necesita la imagen backend local."}]}'
  else
    printf '%s\n' '{"format":1,"checks":[{"code":"DOCKER_UNAVAILABLE","service":"docker","status":"error","action":"Inicia Docker y comprueba el contexto elegido; los servicios no se comprobaron."},{"code":"DIAGNOSTIC_UNAVAILABLE","service":"report","status":"pending","action":"Conserva la instalación; el diagnóstico completo necesita la imagen backend local."}]}'
  fi
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || { partial; exit 1; }
installation=${CERBERUS_INSTALL_DIR:-"$script_dir/../.."}
cd -- "$installation" 2>/dev/null || { partial; exit 1; }
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  partial
  exit 1
fi
docker_ready=true

# Compose interpreta su .env; este lector solo toma puertos decimales, nunca ejecuta el archivo.
http_port=${CERBERUS_HTTP_PORT:-}
identity_port=${CERBERUS_KEYCLOAK_HTTP_PORT:-}
if [ -f .env ]; then
  while IFS='=' read -r key value; do
    value=${value%$'\r'}
    case "$key" in
      CERBERUS_HTTP_PORT) [ -n "$http_port" ] || http_port=$value ;;
      CERBERUS_KEYCLOAK_HTTP_PORT) [ -n "$identity_port" ] || identity_port=$value ;;
    esac
  done < .env
fi
http_port=${http_port:-8080}
identity_port=${identity_port:-8081}
for port in "$http_port" "$identity_port"; do
  if ! [[ "$port" =~ ^[0-9]{1,5}$ ]] || ((10#$port < 1 || 10#$port > 65535)); then
    partial
    exit 1
  fi
done

services=''
for service in setup-secrets setup-sample redis auth-db keycloak setup-identity api worker frontend; do
  container=$(docker compose ps -aq "$service" 2>/dev/null) || continue
  [[ "$container" =~ ^[a-f0-9]{12,64}$ ]] || continue
  template='{"service":"'"$service"'","state":{{json .State.Status}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}"none"{{end}},"exit_code":{{json .State.ExitCode}},"oom_killed":{{json .State.OOMKilled}},"image":{{json .Config.Image}}}'
  record=$(docker inspect --format "$template" "$container" 2>/dev/null) || continue
  [ -z "$services" ] || services+=','
  services+=$record
done

ports=''
for pair in "http:frontend:$http_port" "identity:keycloak:$identity_port"; do
  IFS=: read -r key service port <<< "$pair"
  published=$(docker compose port "$service" 8080 2>/dev/null) || published=''
  state=unknown
  if [ "$published" = "127.0.0.1:$port" ]; then
    state=expected
  elif ( : >"/dev/tcp/127.0.0.1/$port" ) 2>/dev/null; then
    state=busy
  else
    state=free
  fi
  [ -z "$ports" ] || ports+=','
  ports+='"'"$key"'":"'"$state"'"'
done
release='{}'
sample='null'
[ ! -f release.json ] || release=$(cat release.json 2>/dev/null) || release='{}'
[ ! -f tools/release/sample-manifest.json ] || sample=$(cat tools/release/sample-manifest.json 2>/dev/null) || sample='null'
snapshot='{"docker":{"status":"ready"},"services":['"$services"'],"ports":{'"$ports"'},"release":'"$release"',"sample_manifest":'"$sample"'}'

# Si la API está detenida, solo se crea un contenedor temporal sin puertos ni dependencias.
# --pull never impide que diagnosticar instale o actualice imágenes.
result=$(printf '%s' "$snapshot" | docker compose exec -T api python -m cerberus_api.diagnostics --snapshot-stdin 2>/dev/null)
result_code=$?
if [ -z "$result" ]; then
  result=$(printf '%s' "$snapshot" | docker compose run --rm --no-deps --pull never --entrypoint python -T api -m cerberus_api.diagnostics --snapshot-stdin 2>/dev/null)
  result_code=$?
fi
case "$result" in
  '{"format": 1, "checks": ['*) printf '%s\n' "$result"; exit "$result_code" ;;
  *) partial; exit 1 ;;
esac
