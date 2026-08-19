#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/UNICOMFS/shskw43_1/.bihu/interns2-agent-robot/interns2-finetune"
LOG_DIR="$ROOT/logs/services"

usage() {
    echo "Usage:"
    echo "  $0 all"
    echo "  $0 inference"
    echo "  $0 simulation"
    echo "  $0 planner"
    echo "  $0 web"
}

case "${1:-}" in
    all)
        tail -n 100 -F \
            "$LOG_DIR/inference.log" \
            "$LOG_DIR/robot-simulation.log" \
            "$LOG_DIR/planner-adapter.log" \
            "$LOG_DIR/agent-web.log"
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
    *)
        usage
        exit 1
        ;;
esac
