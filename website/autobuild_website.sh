#!/bin/zsh
set -euo pipefail

if [ "$#" -eq 0 ]; then
    set -- build
fi

python "$(dirname "$0")/build_site.py" "$@"
