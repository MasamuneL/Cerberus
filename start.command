#!/usr/bin/env bash
# Finder abre este archivo usando la misma entrada que Linux.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec bash "$root/tools/setup/start.sh" "$@"
