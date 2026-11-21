#!/usr/bin/env bash
# Lanzador de Cerberus con detección de hardware (HW2, docs/PLAN_MVP.md §25). macOS, Linux y WSL2.
# En Windows nativo usa tools/launch/up.ps1 (mismo comportamiento).
#
#   tools/launch/up.sh              detecta y levanta el stack
#   tools/launch/up.sh --dry-run    solo imprime lo que haría
#   tools/launch/up.sh down         baja el stack (y el worker nativo del modo híbrido)
#
# Precedencia de variables: entorno de la terminal > `.env` de la raíz (lo lee Compose) > valor del lanzador >
# default de compose.yaml. El lanzador solo exporta las variables que no están ni en el entorno ni en `.env`.
#
# Detección simulable (pruebas, sin hardware ni daemon):
#   CERBERUS_LAUNCH_FAKE_OS               darwin | linux | wsl | windows
#   CERBERUS_LAUNCH_FAKE_ARCH             arm64 | x86_64 (acepta aarch64/amd64)
#   CERBERUS_LAUNCH_FAKE_NVIDIA_SMI       salida CSV de nvidia-smi («nombre, cc, driver, memoria») o «none»
#   CERBERUS_LAUNCH_FAKE_DOCKER_INFO      «NCPU MemTotal» (bytes), como `docker info --format '{{.NCPU}} {{.MemTotal}}'`
#   CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES  runtimes de Docker separados por espacios (Linux: «runc nvidia»)
#   CERBERUS_LAUNCH_ENV_FILE              `.env` a considerar (por defecto <raíz>/.env)
#   CERBERUS_UV                           binario de uv (si no está en el PATH)
#
# Compatible con bash 3.2 (el de macOS): sin arrays asociativos ni ${var,,}.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Umbrales. LOW_MEMORY_GB repite runtime.LOW_MEMORY_GB (pico del worker ~4.2 GB con 001/t0).
LOW_MEMORY_GB=5
MEM_RESERVED_GB=2 # API (2g), Keycloak, PostgreSQL, Redis y nginx
MEM_MAX_GB=12
GPU_EXTRA_GB=1 # contexto CUDA + cuDNN en el worker
FEW_CPUS=4
CU126_MIN_DRIVER=525
CU130_MIN_DRIVER=580
# Compute capability ×10: la rueda cu126 trae kernels sm_50…sm_90; desde cc 10.0 (Blackwell) hace falta cu130
MIN_CC=50
CU130_MIN_CC=100

ENV_FILE="${CERBERUS_LAUNCH_ENV_FILE:-$ROOT/.env}"

usage() {
  cat <<'EOF'
Uso: tools/launch/up.sh [up|down] [opciones]

Detecta SO, arquitectura, CPU/RAM de Docker y GPU NVIDIA, y levanta Cerberus con lo mejor disponible:
  · NVIDIA (Linux/WSL2/Windows)   docker compose -f compose.yaml -f compose.gpu.yaml (torch cu126 o cu130)
  · macOS Apple Silicon           modo híbrido: compose.hybrid.yaml + worker nativo (MPS y ANTs arm64)
  · resto                         docker compose -f compose.yaml (CPU)

Opciones:
  --dry-run      imprime archivos compose, variables y comandos sin ejecutar nada
  --cpu          ignora la GPU NVIDIA
  --no-hybrid    en Mac Apple Silicon usa el worker de Docker (Rosetta) en vez del nativo
  --fast         aplica CERBERUS_REGISTRATION=fast (registro ANTs rápido) si no lo definiste tú
  --foreground   modo híbrido: el worker nativo corre en esta terminal (Ctrl+C lo detiene)
  -h, --help     esta ayuda

down: detiene el worker nativo (por su PID en storage/launch/) y baja el stack con los mismos -f del arranque.

Las variables que ya definiste (entorno o .env) nunca se sobrescriben. Ver README, «Lanzador».
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

# --- argumentos ---------------------------------------------------------------------------------------------------
ACTION=up
DRY_RUN=0
FORCE_CPU=0
NO_HYBRID=0
FAST=0
FOREGROUND=0
for arg in "$@"; do
  case "$arg" in
    up) ACTION=up ;;
    down) ACTION=down ;;
    --dry-run) DRY_RUN=1 ;;
    --cpu) FORCE_CPU=1 ;;
    --no-hybrid) NO_HYBRID=1 ;;
    --fast) FAST=1 ;;
    --foreground) FOREGROUND=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *) die "opción desconocida: $arg (usa --help)" ;;
  esac
done

# --- variables del usuario ------------------------------------------------------------------------------------------
# Valor de NAME en .env (formato de Compose: KEY=VALUE, comillas opcionales, `# comentario` tras un valor sin comillas).
env_file_value() {
  local name="$1" line value
  [ -f "$ENV_FILE" ] || return 1
  line="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${name}[[:space:]]*=" "$ENV_FILE" | tail -n 1)" || return 1
  value="${line#*=}"
  value="${value#"${value%%[![:space:]]*}"}"
  case "$value" in
    \"*)
      value="${value#\"}"
      value="${value%%\"*}"
      ;;
    \'*)
      value="${value#\'}"
      value="${value%%\'*}"
      ;;
    *)
      value="${value%%[[:space:]]#*}"
      value="${value%"${value##*[![:space:]]}"}"
      ;;
  esac
  printf '%s' "$value"
}

# Origen de una variable definida por el usuario («entorno» o «.env»); vacío si no la definió.
user_source() {
  local name="$1"
  if [ -n "${!name+x}" ]; then
    printf 'entorno'
  elif env_file_value "$name" >/dev/null; then
    printf '.env'
  fi
}

# Valor efectivo de NAME: entorno > .env > default (lo que verá Compose).
effective() {
  local name="$1" default="${2:-}"
  if [ -n "${!name+x}" ]; then
    printf '%s' "${!name}"
  elif env_file_value "$name" >/dev/null; then
    env_file_value "$name"
  else
    printf '%s' "$default"
  fi
}

VARS_REPORT=""
WARNINGS=""
warn() { WARNINGS="${WARNINGS}  ! $*"$'\n'; }

# Fija NAME=VALUE solo si el usuario no la definió; anota el origen en el informe.
propose() {
  local name="$1" value="$2" why="$3" origin
  origin="$(user_source "$name")"
  if [ -n "$origin" ]; then
    VARS_REPORT="${VARS_REPORT}  ${name}=$(effective "$name")  (tuya, ${origin}; el lanzador proponía ${value})"$'\n'
  else
    export "${name}=${value}"
    VARS_REPORT="${VARS_REPORT}  ${name}=${value}  (lanzador: ${why})"$'\n'
  fi
}

# --- detección ----------------------------------------------------------------------------------------------------
detect_os() {
  if [ -n "${CERBERUS_LAUNCH_FAKE_OS:-}" ]; then
    printf '%s' "$CERBERUS_LAUNCH_FAKE_OS"
    return
  fi
  case "$(uname -s)" in
    Darwin) printf 'darwin' ;;
    Linux)
      if grep -qi microsoft /proc/version 2>/dev/null; then printf 'wsl'; else printf 'linux'; fi
      ;;
    MINGW* | MSYS* | CYGWIN*) printf 'windows' ;;
    *) uname -s | tr '[:upper:]' '[:lower:]' ;;
  esac
}

detect_arch() {
  local arch
  if [ -n "${CERBERUS_LAUNCH_FAKE_ARCH:-}" ]; then
    arch="$CERBERUS_LAUNCH_FAKE_ARCH"
  else
    arch="$(uname -m)"
    # Una terminal bajo Rosetta dice x86_64 en un Mac Apple Silicon
    if [ "$arch" = "x86_64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then
      arch=arm64
    fi
  fi
  case "$arch" in
    aarch64 | arm64 | ARM64) printf 'arm64' ;;
    x86_64 | amd64 | AMD64) printf 'x86_64' ;;
    *) printf '%s' "$arch" ;;
  esac
}

docker_info() {
  if [ -n "${CERBERUS_LAUNCH_FAKE_DOCKER_INFO:-}" ]; then
    printf '%s' "$CERBERUS_LAUNCH_FAKE_DOCKER_INFO"
    return
  fi
  command -v docker >/dev/null 2>&1 ||
    die "no encuentro el comando docker. Instala Docker Desktop (o Docker Engine con Compose ≥ 2.24)."
  docker info --format '{{.NCPU}} {{.MemTotal}}' 2>/dev/null ||
    die "Docker no responde. Arranca Docker Desktop (o el servicio docker) y vuelve a intentarlo."
}

docker_runtimes() {
  if [ -n "${CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES+x}" ]; then
    printf '%s' "$CERBERUS_LAUNCH_FAKE_DOCKER_RUNTIMES"
    return
  fi
  docker info --format '{{range $k, $v := .Runtimes}}{{$k}} {{end}}' 2>/dev/null || true
}

# Primera GPU: «nombre, compute_cap, driver, memoria»; vacío si no hay nvidia-smi o no responde.
nvidia_query() {
  if [ -n "${CERBERUS_LAUNCH_FAKE_NVIDIA_SMI:-}" ]; then
    [ "$CERBERUS_LAUNCH_FAKE_NVIDIA_SMI" = "none" ] || printf '%s\n' "$CERBERUS_LAUNCH_FAKE_NVIDIA_SMI" | head -n 1
    return 0
  fi
  command -v nvidia-smi >/dev/null 2>&1 || return 0
  nvidia-smi --query-gpu=name,compute_cap,driver_version,memory.total --format=csv,noheader 2>/dev/null |
    head -n 1 || true
}

trim() {
  local s="$1"
  s="${s#"${s%%[![:space:]]*}"}"
  printf '%s' "${s%"${s##*[![:space:]]}"}"
}

OS="$(detect_os)"
ARCH="$(detect_arch)"
FAKE_NOTE=""
if [ -n "${CERBERUS_LAUNCH_FAKE_OS:-}${CERBERUS_LAUNCH_FAKE_ARCH:-}${CERBERUS_LAUNCH_FAKE_NVIDIA_SMI:-}${CERBERUS_LAUNCH_FAKE_DOCKER_INFO:-}" ]; then
  FAKE_NOTE="  (detección simulada con CERBERUS_LAUNCH_FAKE_*)"
fi

HYBRID=0
if [ "$OS" = "darwin" ] && [ "$ARCH" = "arm64" ] && [ "$NO_HYBRID" -eq 0 ]; then
  HYBRID=1
fi

STORAGE_PATH="$(effective CERBERUS_STORAGE_PATH ./storage)"
LAUNCH_DIR="$STORAGE_PATH/launch"
PID_FILE="$LAUNCH_DIR/worker.pid"
LOG_FILE="$LAUNCH_DIR/worker.log"
STATE_FILE="$LAUNCH_DIR/compose-files"

# PID del worker nativo si sigue vivo y es nuestro (evita matar un proceso ajeno que heredó el número).
native_worker_pid() {
  local pid
  [ -f "$PID_FILE" ] || return 1
  pid="$(tr -cd '0-9' <"$PID_FILE")"
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q 'cerberus_api.worker' || return 1
  printf '%s' "$pid"
}

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  %s\n' "$*"
  else
    printf '+ %s\n' "$*"
    "$@"
  fi
}

# --- down -----------------------------------------------------------------------------------------------------------
if [ "$ACTION" = "down" ]; then
  if [ -f "$STATE_FILE" ]; then
    read -r -a FILES <"$STATE_FILE"
  elif [ "$HYBRID" -eq 1 ]; then
    FILES=(-f compose.yaml -f compose.hybrid.yaml)
  else
    FILES=(-f compose.yaml)
  fi
  [ "$DRY_RUN" -eq 1 ] && printf 'Comandos (--dry-run, no se ejecuta nada):\n'
  if pid="$(native_worker_pid)"; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf '  kill -TERM %s   # worker nativo\n' "$pid"
    else
      printf 'Deteniendo el worker nativo (PID %s)…\n' "$pid"
      kill -TERM "$pid" 2>/dev/null || true
      # Mismo margen que stop_grace_period del worker de Docker
      for _ in $(seq 1 30); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
      done
      if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
      rm -f "$PID_FILE"
    fi
  elif [ "$DRY_RUN" -eq 0 ]; then
    rm -f "$PID_FILE"
  fi
  PROFILE_ARGS=()
  # Con el override híbrido, el perfil también baja un worker de Docker levantado con --profile docker-worker
  case " ${FILES[*]} " in *" compose.hybrid.yaml "*) PROFILE_ARGS=(--profile docker-worker) ;; esac
  run docker compose "${FILES[@]}" "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}" down
  [ "$DRY_RUN" -eq 1 ] || rm -f "$STATE_FILE"
  exit 0
fi

# --- up: decisión ---------------------------------------------------------------------------------------------------
INFO="$(docker_info)"
read -r NCPU MEM_BYTES _ <<<"$INFO"
case "${NCPU:-}" in '' | *[!0-9]*) die "docker info devolvió CPUs no numéricas: «$INFO»" ;; esac
case "${MEM_BYTES:-}" in '' | *[!0-9]*) die "docker info devolvió memoria no numérica: «$INFO»" ;; esac
MEM_GB="$(awk -v b="$MEM_BYTES" 'BEGIN { printf "%.1f", b / 1073741824 }')"

GPU_LINE=""
GPU_DESC="no detectada"
GPU_CC=""
GPU_DRIVER=""
TORCH_VARIANT=""
if [ "$OS" != "darwin" ]; then
  GPU_LINE="$(nvidia_query)"
fi
if [ -n "$GPU_LINE" ]; then
  IFS=',' read -r GPU_NAME GPU_CC GPU_DRIVER GPU_MEM <<<"$GPU_LINE"
  GPU_NAME="$(trim "$GPU_NAME")"
  GPU_CC="$(trim "${GPU_CC:-}")"
  GPU_DRIVER="$(trim "${GPU_DRIVER:-}")"
  GPU_MEM="$(trim "${GPU_MEM:-}")"
  GPU_DESC="$GPU_NAME (cc $GPU_CC, driver $GPU_DRIVER, $GPU_MEM)"
  CC10="$(awk -v c="$GPU_CC" 'BEGIN { if (c ~ /^[0-9]+(\.[0-9]+)?$/) printf "%d", c * 10 + 0.5 }')"
  DRIVER_MAJOR="${GPU_DRIVER%%.*}"
  case "$DRIVER_MAJOR" in '' | *[!0-9]*) DRIVER_MAJOR=0 ;; esac
  if [ "$FORCE_CPU" -eq 1 ]; then
    GPU_DESC="$GPU_DESC · ignorada por --cpu"
  elif [ -z "$CC10" ]; then
    warn "nvidia-smi no informó la compute capability («$GPU_CC»): driver demasiado viejo. Se usa CPU."
  elif [ "$CC10" -lt "$MIN_CC" ]; then
    warn "la GPU tiene cc $GPU_CC y PyTorch exige ≥ 5.0. Se usa CPU."
  elif [ "$OS" = "linux" ] && ! docker_runtimes | grep -qw nvidia; then
    warn "hay GPU NVIDIA pero Docker no tiene el runtime nvidia: instala NVIDIA Container Toolkit y reinicia Docker. Mientras tanto se usa CPU."
  elif [ "$CC10" -ge "$CU130_MIN_CC" ]; then
    if [ "$DRIVER_MAJOR" -ge "$CU130_MIN_DRIVER" ]; then
      TORCH_VARIANT=cu130
    else
      warn "la GPU (cc $GPU_CC, Blackwell) necesita torch cu130 y driver ≥ $CU130_MIN_DRIVER (tienes $GPU_DRIVER): actualiza el driver. Mientras tanto se usa CPU."
    fi
  elif [ "$DRIVER_MAJOR" -ge "$CU126_MIN_DRIVER" ]; then
    TORCH_VARIANT=cu126
  else
    warn "torch cu126 necesita driver NVIDIA ≥ $CU126_MIN_DRIVER (tienes $GPU_DRIVER): actualízalo. Mientras tanto se usa CPU."
  fi
fi

EMULATED=0
if [ "$ARCH" = "arm64" ] && [ "$HYBRID" -eq 0 ]; then
  # La imagen del backend es linux/amd64 (ANTs no publica wheel Linux arm64): en arm64 corre emulada
  EMULATED=1
fi

FILES=(-f compose.yaml)
if [ "$HYBRID" -eq 1 ]; then
  MODE="híbrido (API en Docker + worker nativo con MPS y ANTs arm64)"
  FILES+=(-f compose.hybrid.yaml)
elif [ -n "$TORCH_VARIANT" ]; then
  MODE="gpu NVIDIA (torch $TORCH_VARIANT)"
  FILES+=(-f compose.gpu.yaml)
  propose CERBERUS_TORCH_VARIANT "$TORCH_VARIANT" "cc $GPU_CC, driver $GPU_DRIVER"
  if [ "$(effective CERBERUS_TORCH_VARIANT)" != "$TORCH_VARIANT" ]; then
    warn "CERBERUS_TORCH_VARIANT=$(effective CERBERUS_TORCH_VARIANT) (tuya) difiere de la detectada ($TORCH_VARIANT)."
  fi
elif [ "$EMULATED" -eq 1 ]; then
  MODE="cpu (backend linux/amd64 emulado en $ARCH)"
else
  MODE="cpu"
fi

# Memoria del worker de Docker (en el modo híbrido no hay worker de Docker)
if [ "$HYBRID" -eq 0 ]; then
  MEM_MIN_GB="$LOW_MEMORY_GB"
  if [ -n "$TORCH_VARIANT" ]; then MEM_MIN_GB=$((LOW_MEMORY_GB + GPU_EXTRA_GB)); fi
  MEM_LIMIT_GB="$(awk -v b="$MEM_BYTES" -v r="$MEM_RESERVED_GB" -v lo="$MEM_MIN_GB" -v hi="$MEM_MAX_GB" \
    'BEGIN { g = int(b / 1073741824 - r); if (g < lo) g = lo; if (g > hi) g = hi; print g }')"
  if awk -v b="$MEM_BYTES" -v r="$MEM_RESERVED_GB" -v lo="$MEM_MIN_GB" 'BEGIN { exit !(b / 1073741824 - r < lo) }'; then
    warn "Docker tiene ${MEM_GB} GB: tras reservar ${MEM_RESERVED_GB} GB al resto quedan menos de ${MEM_MIN_GB} GB para el worker (pico ~4.2 GB con 001/t0). Sube la memoria de Docker (Settings → Resources) o el worker puede morir por falta de memoria."
  fi
  propose CERBERUS_WORKER_MEM_LIMIT "${MEM_LIMIT_GB}g" "clamp(${MEM_GB} GB − ${MEM_RESERVED_GB}, ${MEM_MIN_GB}, ${MEM_MAX_GB})"
fi

# Registro rápido: con pocas CPU o emulación el SyN de ANTs domina el tiempo de las áreas
if [ "$NCPU" -le "$FEW_CPUS" ] || [ "$EMULATED" -eq 1 ]; then
  REASON="$NCPU CPU en Docker"
  if [ "$EMULATED" -eq 1 ]; then REASON="emulación $ARCH → amd64"; fi
  if [ "$FAST" -eq 1 ]; then
    propose CERBERUS_REGISTRATION fast "--fast ($REASON)"
  elif [ -z "$(user_source CERBERUS_REGISTRATION)" ]; then
    warn "sugerencia ($REASON): registro rápido con --fast o CERBERUS_REGISTRATION=fast (áreas más rápidas, con menos resolución)."
  fi
elif [ "$FAST" -eq 1 ]; then
  propose CERBERUS_REGISTRATION fast "--fast"
fi

# En Linux (y WSL2) los bind mounts respetan el UID: el contenedor debe escribir ./storage y ./models como tú
if [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
  propose CERBERUS_UID "$(id -u)" "tu usuario"
  propose CERBERUS_GID "$(id -g)" "tu grupo"
fi

UP_CMD=(docker compose "${FILES[@]}" up -d --build)

# Worker nativo del modo híbrido: mismas rutas que los bind mounts y Redis publicado en loopback
UV_BIN=""
REDIS_PORT=""
WORKER_ENV=()
if [ "$HYBRID" -eq 1 ]; then
  UV_BIN="${CERBERUS_UV:-$(command -v uv 2>/dev/null || true)}"
  if [ -z "$UV_BIN" ]; then
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv; do
      if [ -x "$candidate" ]; then
        UV_BIN="$candidate"
        break
      fi
    done
  fi
  REDIS_PORT="$(effective CERBERUS_REDIS_PORT 6379)"
  REDIS_URL="redis://127.0.0.1:${REDIS_PORT}/0"
  if [ -n "${CERBERUS_REDIS_URL+x}" ] && [ "$CERBERUS_REDIS_URL" != "$REDIS_URL" ]; then
    warn "CERBERUS_REDIS_URL=$CERBERUS_REDIS_URL (tuya) se respeta, pero el Redis del stack está en $REDIS_URL."
    REDIS_URL="$CERBERUS_REDIS_URL"
  fi
  WORKER_ENV=("CERBERUS_REDIS_URL=$REDIS_URL")
  for pair in DATA:./Data STORAGE:./storage MODELS:./models; do
    kind="${pair%%:*}"
    path_value="$(effective "CERBERUS_${kind}_PATH" "${pair#*:}")"
    dir_name="CERBERUS_${kind}_DIR"
    if [ -n "${!dir_name+x}" ]; then
      if [ "${!dir_name}" != "$path_value" ]; then
        warn "$dir_name=${!dir_name} (tuya) difiere de CERBERUS_${kind}_PATH=$path_value: la API de Docker no verá esos archivos."
      fi
      WORKER_ENV+=("$dir_name=${!dir_name}")
    else
      WORKER_ENV+=("$dir_name=$path_value")
    fi
  done
  # El worker nativo no lee .env: se le pasan los mismos valores efectivos que ve Compose
  for name in CERBERUS_CPU_THREADS CERBERUS_REGISTRATION; do
    value="$(effective "$name")"
    if [ -n "$value" ]; then WORKER_ENV+=("$name=$value"); fi
  done
fi
WORKER_CMD=(env "${WORKER_ENV[@]+"${WORKER_ENV[@]}"}" "${UV_BIN:-uv}" run --no-sync python -m cerberus_api.worker)

# --- informe ------------------------------------------------------------------------------------------------------
printf 'Cerberus · lanzador (HW2)%s\n' "$FAKE_NOTE"
printf '  Sistema:  %s/%s\n' "$OS" "$ARCH"
printf '  Docker:   %s CPU · %s GB\n' "$NCPU" "$MEM_GB"
printf '  GPU:      %s\n' "$GPU_DESC"
printf '  Modo:     %s\n' "$MODE"
printf '  Compose:  %s\n' "${FILES[*]}"
printf 'Variables:\n'
if [ -n "$VARS_REPORT" ]; then printf '%s' "$VARS_REPORT"; else printf '  (ninguna)\n'; fi
if [ -n "$WARNINGS" ]; then printf 'Avisos:\n%s' "$WARNINGS"; fi

if [ "$DRY_RUN" -eq 1 ]; then
  printf 'Comandos (--dry-run, no se ejecuta nada):\n'
  printf '  %s\n' "${UP_CMD[*]}"
  if [ "$HYBRID" -eq 1 ]; then
    printf '  %s sync\n' "${UV_BIN:-uv}"
    if [ "$FOREGROUND" -eq 1 ]; then
      printf '  %s\n' "${WORKER_CMD[*]}"
    else
      printf '  %s > %s 2>&1 &   # PID en %s\n' "${WORKER_CMD[*]}" "$LOG_FILE" "$PID_FILE"
    fi
  fi
  exit 0
fi

# --- up: ejecución ------------------------------------------------------------------------------------------------
docker compose version >/dev/null 2>&1 || die "falta Docker Compose v2 (docker compose). Actualiza Docker."
if [ "$HYBRID" -eq 1 ]; then
  [ -n "$UV_BIN" ] ||
    die "el modo híbrido necesita uv (https://docs.astral.sh/uv/) o CERBERUS_UV=/ruta/a/uv. Alternativa: --no-hybrid."
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$REDIS_PORT" -sTCP:LISTEN >/dev/null 2>&1 &&
    [ -z "$(docker compose "${FILES[@]}" ps --status running -q redis 2>/dev/null)" ]; then
    die "el puerto $REDIS_PORT ya está en uso (¿un redis-server local?). Exporta CERBERUS_REDIS_PORT=6390 (u otro libre) y reintenta."
  fi
fi

mkdir -p "$LAUNCH_DIR"
run "${UP_CMD[@]}"
printf '%s\n' "${FILES[*]}" >"$STATE_FILE"

HTTP_PORT="$(effective CERBERUS_HTTP_PORT 8080)"
if [ "$HYBRID" -eq 1 ]; then
  if pid="$(native_worker_pid)"; then
    printf 'El worker nativo ya corre (PID %s; log en %s).\n' "$pid" "$LOG_FILE"
  else
    run "$UV_BIN" sync
    if [ "$FOREGROUND" -eq 1 ]; then
      printf 'App: http://localhost:%s · worker nativo en primer plano (Ctrl+C lo detiene; después tools/launch/up.sh down).\n' "$HTTP_PORT"
      exec "${WORKER_CMD[@]}"
    fi
    printf '+ %s > %s 2>&1 &\n' "${WORKER_CMD[*]}" "$LOG_FILE"
    nohup "${WORKER_CMD[@]}" >"$LOG_FILE" 2>&1 &
    printf '%s\n' "$!" >"$PID_FILE"
    sleep 3
    native_worker_pid >/dev/null || die "el worker nativo terminó al arrancar; revisa $LOG_FILE"
    printf 'Worker nativo en segundo plano (PID %s; log en %s).\n' "$(cat "$PID_FILE")" "$LOG_FILE"
  fi
fi
printf 'App: http://localhost:%s · para bajar: tools/launch/up.sh down\n' "$HTTP_PORT"
