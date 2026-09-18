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
import json
import urllib.request

services = [
    ("interns2-inference", 23333, "/v1/models"),
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

try:
    with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=3) as response:
        robot = json.load(response)
    if robot.get("runtime_mode") == "real":
        real_ok = (
            robot.get("control_mode") == "observe-only"
            and robot.get("provider") == "huayan_edge_gateway"
            and robot.get("status") in {"healthy", "degraded"}
            and robot.get("ready_for_motion") is False
            and robot.get("error") in {
                None, "gateway_disconnected", "datasheet_disconnected",
                "datasheet_stale", "command_socket_disconnected",
            }
        )
        mode = "REAL / OBSERVE ONLY" if real_ok else "REAL / MODE MISMATCH"
        detail = (
            "MODE MISMATCH" if not real_ok else
            "HEALTHY (state fresh, observe-only)" if robot.get("status") == "healthy"
            else f"DEGRADED ({robot.get('error')})"
        )
    else:
        mode = "SIMULATION"
        detail = "HEALTHY" if robot.get("service") == "robot-simulation" and robot.get("ready") else "UNAVAILABLE"
    state = "RUNNING" if detail not in {"MODE MISMATCH", "UNAVAILABLE"} else "DOWN"
except Exception:
    mode, state, detail = "UNKNOWN", "DOWN", "UNAVAILABLE"
robot_name = "robot-runtime" if mode.startswith("REAL") else "robot-simulation"
print(f"{robot_name:22} {state:9} :{8001:<5}  {detail}")

try:
    with urllib.request.urlopen("http://127.0.0.1:8002/health", timeout=3) as response:
        planner_healthy = 200 <= response.status < 300
except Exception:
    planner_healthy = False
print(f"{'planner-adapter':22} {'RUNNING' if planner_healthy else 'DOWN':9} :{8002:<5}  {'HEALTHY' if planner_healthy else 'UNAVAILABLE'}")

try:
    with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
        web = json.load(response)
    expected = "real" if mode.startswith("REAL") else "simulation"
    healthy = mode != "UNKNOWN" and web.get("runtime_mode") == expected
    if mode.startswith("REAL"):
        healthy = healthy and web.get("control_mode") == "observe-only"
except Exception:
    healthy = False
print(f"{'agent-web':22} {'RUNNING' if healthy else 'DOWN':9} :{8000:<5}  {'HEALTHY' if healthy else 'MODE MISMATCH / UNAVAILABLE'}")
print(f"ROBOT MODE = {mode}")

print("==================================================")
PY
