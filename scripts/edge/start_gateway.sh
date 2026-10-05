#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"

# 默认使用 course 虚拟环境
EDGE_PYTHON="${EDGE_PYTHON:-/Users/bigcat/Documents/internS/venv/course/bin/python}"

cd "$APP_ROOT"

export PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# 如果没有传任何参数，就使用真机 Gateway 的默认配置
if (( $# == 0 )); then
    set -- \
        --real-config configs/robot-real.local.yaml \
        --connect-real \
        --server-url ws://127.0.0.1:18001/v1/gateway/connect \
        --secret-file configs/gateway-auth.local \
        --gateway-id mac-huayan-ph590320009 \
        --datasheet-byte-order little \
        --audit-path logs/edge_gateway.log
fi

exec "$EDGE_PYTHON" -m edge_gateway.main "$@"