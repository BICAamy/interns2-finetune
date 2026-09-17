#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
PYTHON="$BUNDLE_ROOT/runtime/envs/agent-web/bin/python"

test -x "$PYTHON" || {
    echo "ERROR: agent-web runtime is missing at $PYTHON." >&2
    echo "Run the bundle's scripts/bootstrap.sh first." >&2
    exit 1
}

"$PYTHON" - <<'PY'
import sys
import urllib.request

services = [
    ("InternS2 inference", "http://127.0.0.1:23333/v1/models"),
    ("robot-simulation", "http://127.0.0.1:8001/health"),
    ("planner-adapter", "http://127.0.0.1:8002/health"),
    ("agent-web", "http://127.0.0.1:8000/health"),
]

failed = False

print("========================================")
print(" InternS2 Service Health Check")
print("========================================")

for name, url in services:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            ok = 200 <= response.status < 300
            status = f"HTTP {response.status}"
    except Exception as exc:
        ok = False
        status = str(exc)

    print(f"{name:20} : {'HEALTHY' if ok else 'FAILED'}")
    if not ok:
        print(f"  {status}")
        failed = True

print("========================================")

if failed:
    print("HEALTH CHECK = FAILED")
    sys.exit(1)

print("HEALTH CHECK = PASS")
PY
