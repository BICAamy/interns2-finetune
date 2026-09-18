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
import json
import sys
import urllib.request

services = [
    ("InternS2 inference", "http://127.0.0.1:23333/v1/models"),
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

robot_health = None
web_health = None
try:
    with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=3) as response:
        robot_health = json.load(response)
    if robot_health.get("runtime_mode") == "real":
        robot_ok = (
            robot_health.get("control_mode") == "observe-only"
            and robot_health.get("provider") == "huayan_edge_gateway"
            and robot_health.get("status") in {"healthy", "degraded"}
            and robot_health.get("error") in {
                None, "gateway_disconnected", "datasheet_disconnected",
                "datasheet_stale", "command_socket_disconnected",
            }
            and robot_health.get("ready_for_motion") is False
        )
        mode = "REAL / OBSERVE ONLY" if robot_ok else "REAL / MODE MISMATCH"
        robot_status = (
            "FAILED" if not robot_ok else
            "HEALTHY (state fresh, observe-only)" if robot_health.get("status") == "healthy"
            else f"DEGRADED ({robot_health.get('error')})"
        )
    else:
        mode = "SIMULATION"
        robot_ok = robot_health.get("service") == "robot-simulation" and robot_health.get("ready") is True
        robot_status = "HEALTHY" if robot_ok else "FAILED"
except Exception as exc:
    mode = "UNKNOWN"
    robot_ok = False
    robot_status = f"FAILED ({exc})"
robot_name = "robot-runtime" if mode.startswith("REAL") else "robot-simulation"
print(f"{robot_name:20} : {robot_status}")
failed |= not robot_ok

try:
    with urllib.request.urlopen("http://127.0.0.1:8002/health", timeout=3) as response:
        planner_ok = 200 <= response.status < 300
except Exception as exc:
    planner_ok = False
    print(f"  planner-adapter error: {exc}")
print(f"{'planner-adapter':20} : {'HEALTHY' if planner_ok else 'FAILED'}")
failed |= not planner_ok

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
        web_health = json.load(response)
    expected_mode = "real" if mode.startswith("REAL") else "simulation"
    web_ok = robot_ok and web_health.get("runtime_mode") == expected_mode
    if mode.startswith("REAL"):
        web_ok = web_ok and web_health.get("control_mode") == "observe-only"
except Exception as exc:
    web_ok = False
    print(f"  agent-web error: {exc}")
print(f"{'agent-web':20} : {'HEALTHY' if web_ok else 'FAILED'}")
failed |= not web_ok
print(f"ROBOT MODE = {mode}")

print("========================================")

if failed:
    print("HEALTH CHECK = FAILED")
    sys.exit(1)

print("HEALTH CHECK = PASS" + (" (OBSERVE ONLY)" if mode.startswith("REAL") else ""))
PY
