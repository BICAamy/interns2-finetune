#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
PYTHON="$BUNDLE_ROOT/runtime/envs/agent-web/bin/python"

test -x "$PYTHON" || {
    echo "ERROR: agent-web runtime is missing at $PYTHON." >&2
    exit 1
}

"$PYTHON" - <<'PY'
import urllib.request

services = [
    ("interns2-inference", 23333, "/v1/models"),
    ("robot-simulation", 8001, "/health"),
    ("planner-adapter", 8002, "/health"),
    ("agent-web", 8000, "/health"),
]

print("==================================================")
print(" Surgical Navigation Service Status")
print("==================================================")

for name, port, path in services:
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            healthy = 200 <= response.status < 300
    except Exception:
        healthy = False

    state = "RUNNING" if healthy else "DOWN"
    detail = "HEALTHY" if healthy else "UNAVAILABLE"
    print(f"{name:22} {state:9} :{port:<5}  {detail}")

print("==================================================")
PY
