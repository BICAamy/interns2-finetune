#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
LOG_DIR="$APP_ROOT/logs/services"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
PYTHON="$BUNDLE_ROOT/runtime/envs/agent-web/bin/python"

if [[ -x "$PYTHON" ]]; then
    mode="$($PYTHON - <<'PY' 2>/dev/null || true
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=2) as response:
    health = json.load(response)
if health.get("runtime_mode") == "real":
    print("REAL / OBSERVE ONLY" if health.get("control_mode") == "observe-only" else "REAL / MODE MISMATCH")
elif health.get("service") == "robot-simulation":
    print("SIMULATION")
else:
    print("UNKNOWN")
PY
)"
else
    mode=""
fi
echo "ROBOT MODE = ${mode:-UNKNOWN (service unavailable)}"

usage() {
    echo "Usage:"
    echo "  $0 all"
    echo "  $0 inference"
    echo "  $0 simulation"
    echo "  $0 robot"
    echo "  $0 planner"
    echo "  $0 web"
    echo "  $0 xvfb"
}

case "${1:-}" in
    all)
        files=()
        if [[ "$mode" == REAL* ]]; then
            names=(inference robot-runtime planner-adapter agent-web)
        elif [[ "$mode" == SIMULATION ]]; then
            names=(inference robot-simulation planner-adapter agent-web xvfb)
        else
            names=(inference robot-simulation robot-runtime planner-adapter agent-web xvfb)
        fi
        for name in "${names[@]}"; do
            [[ -f "$LOG_DIR/$name.log" ]] && files+=("$LOG_DIR/$name.log")
        done
        (( ${#files[@]} > 0 )) || { echo "No service logs found." >&2; exit 1; }
        tail -n 100 -F "${files[@]}"
        ;;
    inference)
        tail -n 200 -F "$LOG_DIR/inference.log"
        ;;
    simulation)
        tail -n 200 -F "$LOG_DIR/robot-simulation.log"
        ;;
    robot)
        if [[ "$mode" == REAL* ]]; then
            tail -n 200 -F "$LOG_DIR/robot-runtime.log"
        else
            tail -n 200 -F "$LOG_DIR/robot-simulation.log"
        fi
        ;;
    planner)
        tail -n 200 -F "$LOG_DIR/planner-adapter.log"
        ;;
    web)
        tail -n 200 -F "$LOG_DIR/agent-web.log"
        ;;
    xvfb)
        tail -n 200 -F "$LOG_DIR/xvfb.log"
        ;;
    *)
        usage
        exit 1
        ;;
esac
