#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
LOG_DIR="$APP_ROOT/logs/services"

usage() {
    echo "Usage:"
    echo "  $0 all"
    echo "  $0 inference"
    echo "  $0 simulation"
    echo "  $0 planner"
    echo "  $0 web"
    echo "  $0 xvfb"
}

case "${1:-}" in
    all)
        tail -n 100 -F \
            "$LOG_DIR/inference.log" \
            "$LOG_DIR/robot-simulation.log" \
            "$LOG_DIR/planner-adapter.log" \
            "$LOG_DIR/agent-web.log" \
            "$LOG_DIR/xvfb.log"
        ;;
    inference)
        tail -n 200 -F "$LOG_DIR/inference.log"
        ;;
    simulation)
        tail -n 200 -F "$LOG_DIR/robot-simulation.log"
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
