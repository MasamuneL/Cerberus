#!/usr/bin/env bash
# El directorio de trabajo del usuario no cambia la instalación seleccionada.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec bash "$root/tools/setup/start.sh" "$@"
