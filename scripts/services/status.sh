#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
PYTHON="$BUNDLE_ROOT/runtime/envs/agent-web/bin/python"
SERVICE_STATE_DIR="${SERVICE_STATE_DIR:-$APP_ROOT/run/services}"
SUPERVISOR_PID_FILE="$SERVICE_STATE_DIR/start_all.pid"
SUPERVISOR_STATE_FILE="$SERVICE_STATE_DIR/start_all.state"
WEB_VARIANT_FILE="$SERVICE_STATE_DIR/web_variant"

# shellcheck source=scripts/services/interns2_config.sh
source "$SCRIPT_DIR/interns2_config.sh"

test -x "$PYTHON" || {
    echo "ERROR: agent-web runtime is missing at $PYTHON." >&2
    exit 1
}

interns2_configure "$APP_ROOT" || exit 1

INTERNS2_ACTIVE_WEB_VARIANT="unknown"
if [[ -r "$WEB_VARIANT_FILE" ]]; then
    IFS= read -r INTERNS2_ACTIVE_WEB_VARIANT < "$WEB_VARIANT_FILE" || true
fi
export INTERNS2_ACTIVE_WEB_VARIANT

INTERNS2_SUPERVISOR_PID="unknown"
INTERNS2_SUPERVISOR_STATE="stopped"
if [[ -r "$SUPERVISOR_PID_FILE" ]]; then
    IFS= read -r INTERNS2_SUPERVISOR_PID < "$SUPERVISOR_PID_FILE" || true
fi
if [[ -r "$SUPERVISOR_STATE_FILE" ]]; then
    IFS= read -r INTERNS2_SUPERVISOR_STATE < "$SUPERVISOR_STATE_FILE" || true
fi
if [[ "$INTERNS2_SUPERVISOR_PID" =~ ^[1-9][0-9]*$ ]] \
    && kill -0 "$INTERNS2_SUPERVISOR_PID" 2>/dev/null \
    && [[ "$(ps -p "$INTERNS2_SUPERVISOR_PID" -o args= 2>/dev/null || true)" == *"scripts/services/start_all.sh"* ]]; then
    INTERNS2_SUPERVISOR_RUNNING=true
else
    INTERNS2_SUPERVISOR_RUNNING=false
fi
export INTERNS2_SUPERVISOR_PID INTERNS2_SUPERVISOR_STATE INTERNS2_SUPERVISOR_RUNNING

"$PYTHON" - <<'PY'
import json
import os
import urllib.request
from urllib.parse import urlsplit

inference_mode = os.environ["INTERNS2_INFERENCE_MODE"]
inference_url = os.environ["INTERNS2_BASE_URL"].rstrip("/") + "/models"
api_key = os.environ["INTERNS2_API_KEY"]

print("==================================================")
print(" Surgical Navigation Service Status")
print("==================================================")
print(f"WEB UI = {os.environ.get('INTERNS2_ACTIVE_WEB_VARIANT', 'unknown')}")
supervisor_running = os.environ.get("INTERNS2_SUPERVISOR_RUNNING") == "true"
supervisor_pid = os.environ.get("INTERNS2_SUPERVISOR_PID", "unknown")
supervisor_state = os.environ.get("INTERNS2_SUPERVISOR_STATE", "unknown")
print(
    f"{'service-supervisor':22} "
    f"{'RUNNING' if supervisor_running else 'DOWN':9} "
    f"pid={supervisor_pid:8}  {supervisor_state}"
)

headers = {}
if api_key != "EMPTY":
    headers["Authorization"] = f"Bearer {api_key}"
try:
    request = urllib.request.Request(inference_url, headers=headers)
    with urllib.request.urlopen(request, timeout=3) as response:
        inference_healthy = 200 <= response.status < 300
except Exception:
    inference_healthy = False
inference_state = "RUNNING" if inference_healthy else "DOWN"
inference_detail = "HEALTHY" if inference_healthy else "UNAVAILABLE"
endpoint = urlsplit(inference_url)
endpoint_label = endpoint.netloc or inference_url
print(
    f"{'interns2-inference':22} {inference_state:9} "
    f"{endpoint_label:20}  {inference_detail} ({inference_mode})"
)

try:
    with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=3) as response:
        robot = json.load(response)
    if robot.get("runtime_mode") == "real":
        real_ok = (
            robot.get("provider") == "huayan_edge_gateway"
            and robot.get("status") in {"healthy", "degraded"}
            and robot.get("error") in {
                None, "gateway_disconnected", "datasheet_disconnected",
                "datasheet_stale", "command_socket_disconnected",
            }
        )
        mode = "REAL" if real_ok else "REAL / MODE MISMATCH"
        detail = (
            "MODE MISMATCH" if not real_ok else
            "HEALTHY (state fresh)" if robot.get("status") == "healthy"
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

fallback_healthy = True
if mode.startswith("REAL"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8003/health", timeout=3) as response:
            fallback = json.load(response)
        fallback_healthy = (
            fallback.get("service") == "robot-simulation"
            and fallback.get("ready") is True
        )
    except Exception:
        fallback_healthy = False
    print(
        f"{'simulation-fallback':22} "
        f"{'RUNNING' if fallback_healthy else 'DOWN':9} :{8003:<5}  "
        f"{'HEALTHY' if fallback_healthy else 'UNAVAILABLE'}"
    )

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
        healthy = (
            healthy
            and fallback_healthy
            and web.get("default_robot_mode") == "simulation"
            and set(web.get("available_robot_modes", [])) == {"simulation", "real"}
        )
except Exception:
    healthy = False
print(f"{'agent-web':22} {'RUNNING' if healthy else 'DOWN':9} :{8000:<5}  {'HEALTHY' if healthy else 'MODE MISMATCH / UNAVAILABLE'}")
print(f"ROBOT MODE = {mode}")

print("==================================================")
PY
