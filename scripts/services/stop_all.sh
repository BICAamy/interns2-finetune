#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
SERVICE_STATE_DIR="${SERVICE_STATE_DIR:-$APP_ROOT/run/services}"
SUPERVISOR_PID_FILE="$SERVICE_STATE_DIR/start_all.pid"
INFERENCE_MODE_FILE="$SERVICE_STATE_DIR/inference_mode"
WEB_VARIANT_FILE="$SERVICE_STATE_DIR/web_variant"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-20}"

usage() {
    echo "Usage: $0"
    echo "Stop the service stack launched by scripts/services/start_all.sh."
}

if (( $# > 0 )); then
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
fi

[[ "$STOP_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: STOP_TIMEOUT_SECONDS must be a positive integer." >&2
    exit 2
}

process_is_running() {
    local pid="$1"
    local state=""
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    state="$(ps -p "$pid" -o stat= 2>/dev/null | tr -d '[:space:]')"
    [[ -n "$state" && "$state" != Z* ]]
}

is_start_all_supervisor() {
    local pid="$1"
    local command=""
    local process_cwd=""
    process_is_running "$pid" || return 1
    command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    [[ "$command" == *"scripts/services/start_all.sh"* ]] || return 1

    # Linux exposes the process cwd. Use it to avoid stopping a similarly
    # named script from another checkout. Other systems still get the exact
    # command-line check above.
    if [[ -L "/proc/$pid/cwd" ]]; then
        process_cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
        [[ "$process_cwd" == "$APP_ROOT" ]] || return 1
    fi
}

read_recorded_pid() {
    local recorded=""
    if [[ -r "$SUPERVISOR_PID_FILE" ]]; then
        IFS= read -r recorded < "$SUPERVISOR_PID_FILE" || true
    fi
    printf '%s' "$recorded"
}

find_supervisor() {
    local recorded=""
    local candidate=""
    local matches=()

    recorded="$(read_recorded_pid)"
    if is_start_all_supervisor "$recorded"; then
        printf '%s' "$recorded"
        return 0
    fi

    # Compatibility path for stacks started before the PID-file support was
    # added. Restrict candidates to the current user and validate each one.
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] || continue
        if is_start_all_supervisor "$candidate"; then
            matches+=("$candidate")
        fi
    done < <(pgrep -u "$(id -u)" -f '[/]scripts/services/start_all\.sh' || true)

    if (( ${#matches[@]} == 1 )); then
        printf '%s' "${matches[0]}"
        return 0
    fi
    if (( ${#matches[@]} > 1 )); then
        echo "ERROR: multiple matching start_all.sh supervisors found: ${matches[*]}" >&2
        return 2
    fi
    return 1
}

INFERENCE_MODE="unknown"
if [[ -r "$INFERENCE_MODE_FILE" ]]; then
    IFS= read -r INFERENCE_MODE < "$INFERENCE_MODE_FILE" || true
fi

set +e
SUPERVISOR_PID="$(find_supervisor)"
FIND_STATUS=$?
set -e

if (( FIND_STATUS == 2 )); then
    exit 1
fi
if (( FIND_STATUS != 0 )); then
    rm -f -- "$SUPERVISOR_PID_FILE" "$INFERENCE_MODE_FILE" "$WEB_VARIANT_FILE"
    echo "No running InternS2 surgical-navigation service stack was found."
    exit 0
fi

echo "Stopping InternS2 surgical-navigation services (supervisor PID=$SUPERVISOR_PID)..."
kill -TERM "$SUPERVISOR_PID"

deadline=$((SECONDS + STOP_TIMEOUT_SECONDS))
while process_is_running "$SUPERVISOR_PID" && (( SECONDS < deadline )); do
    sleep 0.2
done

if process_is_running "$SUPERVISOR_PID"; then
    echo "ERROR: start_all.sh did not stop within ${STOP_TIMEOUT_SECONDS}s." >&2
    echo "The script did not use SIGKILL; inspect the process before retrying." >&2
    exit 1
fi

rm -f -- "$SUPERVISOR_PID_FILE" "$INFERENCE_MODE_FILE" "$WEB_VARIANT_FILE"
echo "All services managed by start_all.sh have stopped."

case "$INFERENCE_MODE" in
    api)
        echo "The external InternS2 API/model service is still running; only this project's client stack stopped."
        ;;
    local)
        echo "The local LMDeploy model service started by this project has also stopped."
        ;;
    *)
        echo "Inference mode was not recorded; only processes owned by start_all.sh were stopped."
        ;;
esac
