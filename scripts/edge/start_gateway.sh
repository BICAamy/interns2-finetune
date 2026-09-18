#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
EDGE_PYTHON="${EDGE_PYTHON:-python3}"

cd "$APP_ROOT"
export PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$EDGE_PYTHON" -m edge_gateway.main "$@"
