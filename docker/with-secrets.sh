#!/bin/bash
# Turn secret files into environment variables, then start the real command.
#   /run/secrets/dlt-password  ->  DLT_PASSWORD
# If a variable is already set, it is left alone.

set -euo pipefail

dir="${SECRETS_DIR:-/run/secrets}"
if [ -d "$dir" ]; then
  for f in "$dir"/*; do
    [ -f "$f" ] || continue                
    name="$(basename "$f")"                
    name="${name%.txt}"         
    var="${name//-/_}"                     
    var="${var^^}"                         
    if [ -z "${!var:-}" ]; then          
      export "$var"="$(tr -d '\r\n' < "$f")"
    fi
  done
fi

exec "$@"  