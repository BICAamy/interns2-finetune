#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
RUNTIME_ROOT="$BUNDLE_ROOT/runtime/envs"
LOG_DIR="$APP_ROOT/logs/services"

INFERENCE_ENV="$RUNTIME_ROOT/inference"
PLANNER_ENV="$RUNTIME_ROOT/planner"
SIM_ENV="$RUNTIME_ROOT/simulation"
AGENT_WEB_ENV="$RUNTIME_ROOT/agent-web"

SOFA_ROOT="$BUNDLE_ROOT/software/SOFA_v24.06.00_Linux"
SOFAPYTHON3_ROOT="$SOFA_ROOT/plugins/SofaPython3"
E05_MODEL_DIR="$BUNDLE_ROOT/software/huayan-elfin-model/model/485/elfin5"

MODEL_DIR="${INTERNS2_MODEL_DIR:-$APP_ROOT/models/Intern-S2-Preview}"
INFERENCE_GPUS="${INFERENCE_CUDA_VISIBLE_DEVICES:-0,1,2,3}"
INFERENCE_TP="${INFERENCE_TP:-4}"
XVFB_DISPLAY="${XVFB_DISPLAY:-99}"

# CUDA 12.8 is installed next to the bundle on the RTX 5090 server. Keep
# operator overrides, while making this app-local entry point self-contained.
CUDA_TOOLKIT_ROOT="${CUDA_HOME:-$BUNDLE_ROOT/../conda_envs/cuda128}"
export CUDA_HOME="$CUDA_TOOLKIT_ROOT"
export CUDA_PATH="$CUDA_TOOLKIT_ROOT"
export PATH="$CUDA_TOOLKIT_ROOT/bin:$PATH"
export NCCL_P2P_DISABLE="${NCCL_P2P_DISABLE:-1}"
export NCCL_IB_DISABLE="${NCCL_IB_DISABLE:-1}"
export NCCL_CUMEM_HOST_ENABLE="${NCCL_CUMEM_HOST_ENABLE:-0}"
export NCCL_SHM_DISABLE="${NCCL_SHM_DISABLE:-0}"

cd "$APP_ROOT"

PIDS=()

cleanup() {
    trap - INT TERM EXIT

    echo
    echo "Stopping surgical-navigation services..."

    for pid in "${PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        kill "$pid" 2>/dev/null || true
    done

    sleep 1

    for pid in "${PIDS[@]:-}"; do
        [[ -n "$pid" ]] || continue
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    wait 2>/dev/null || true

    echo "All services stopped."
}

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

check_model() {
    "$INFERENCE_ENV/bin/python" - "$MODEL_DIR" <<'PY_MODEL'
from pathlib import Path
import json
import sys

root = Path(sys.argv[1])
index_file = root / "model.safetensors.index.json"

if not index_file.is_file():
    raise SystemExit(1)

try:
    data = json.loads(index_file.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(1)

weight_map = data.get("weight_map")
if not isinstance(weight_map, dict) or not weight_map:
    raise SystemExit(1)

shards = set(str(v) for v in weight_map.values())

for shard in shards:
    path = root / shard
    if not path.is_file() or path.stat().st_size <= 0:
        raise SystemExit(1)
PY_MODEL
}

check_ports_free() {
    "$PLANNER_ENV/bin/python" - <<'PY_PORTS'
import socket
import sys

ports = (23333, 8002, 8001, 8000)
busy = []

for port in ports:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        if connection.connect_ex(("127.0.0.1", port)) == 0:
            busy.append(port)

if busy:
    print(f"ERROR: service ports already in use: {busy}", file=sys.stderr)
    print("Stop the existing stack before starting this one.", file=sys.stderr)
    raise SystemExit(1)
PY_PORTS
}


wait_http() {
    local name="$1"
    local url="$2"
    local timeout_s="$3"
    local log_file="$4"

    local deadline=$((SECONDS + timeout_s))

    printf "Waiting for %-20s " "$name"

    while (( SECONDS < deadline )); do
        if "$PLANNER_ENV/bin/python" - "$url" >/dev/null 2>&1 <<'PY_HTTP'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
        if 200 <= response.status < 300:
            raise SystemExit(0)
except Exception:
    pass

raise SystemExit(1)
PY_HTTP
        then
            echo "HEALTHY"
            return 0
        fi

        printf "."
        sleep 2
    done

    echo
    echo "ERROR: $name did not become healthy."
    echo "Last 80 log lines:"
    tail -n 80 "$log_file" || true
    return 1
}


echo "=================================================="
echo " InternS2 Surgical Navigation - Portable Dev"
echo "=================================================="
echo
echo "BUNDLE_ROOT = $BUNDLE_ROOT"
echo "APP_ROOT    = $APP_ROOT"
echo "MODEL_DIR   = $MODEL_DIR"
echo

# Real-mode CLI is introduced in Step 3. Do not silently ignore a requested
# mode and accidentally launch the current simulation-only stack instead.
if (( $# != 0 )); then
    fail "Unsupported arguments; this launcher currently starts simulation only."
fi

# --------------------------------------------------
# Preflight (before creating logs or starting services)
# --------------------------------------------------

echo "===== preflight ====="

test -d "$APP_ROOT/.git" \
    || fail "app/.git is missing; development repository is incomplete."

for env_name in inference planner simulation agent-web; do
    test -x "$RUNTIME_ROOT/$env_name/bin/python" \
        || fail "$env_name runtime is missing. Run bundle scripts/bootstrap.sh first."
done

test -x "$INFERENCE_ENV/bin/lmdeploy" \
    || fail "lmdeploy is missing from inference environment."

test -x "$SIM_ENV/bin/Xvfb" \
    || fail "Xvfb is missing from simulation environment."

test -x "$CUDA_TOOLKIT_ROOT/bin/nvcc" \
    || fail "CUDA 12.8 toolkit is missing at $CUDA_TOOLKIT_ROOT."

CUDA_VERSION_OUTPUT="$("$CUDA_TOOLKIT_ROOT/bin/nvcc" --version)" \
    || fail "Could not query CUDA toolkit at $CUDA_TOOLKIT_ROOT."
[[ "$CUDA_VERSION_OUTPUT" == *"release 12.8"* ]] \
    || fail "Expected CUDA 12.8 at $CUDA_TOOLKIT_ROOT."

test -x "$SOFA_ROOT/bin/runSofa" \
    || fail "SOFA runtime is missing."

test -d "$SOFAPYTHON3_ROOT" \
    || fail "SofaPython3 is missing."

test -d "$E05_MODEL_DIR" \
    || fail "E05 model directory is missing."

test -f "$APP_ROOT/models/asr/faster-whisper-small/model.bin" \
    || fail "ASR model is missing."

test -f "$APP_ROOT/web/frontend/dist/index.html" \
    || fail "frontend dist is missing. Build web/frontend first."

if ! check_model; then
    echo
    echo "ERROR: Intern-S2-Preview weights are incomplete:"
    echo "  $MODEL_DIR"
    echo
    echo "On a newly extracted bundle, run:"
    echo "  $BUNDLE_ROOT/scripts/download_interns2.sh"
    exit 1
fi

check_ports_free || fail "Refusing to launch beside an existing service stack."

mkdir -p "$LOG_DIR"

echo "Intern-S2 model = OK"
echo "CUDA toolkit    = $CUDA_TOOLKIT_ROOT"
echo "SOFA            = OK"
echo "E05             = OK"
echo "ASR             = OK"
echo "frontend dist   = OK"
echo

trap cleanup INT TERM EXIT


# --------------------------------------------------
# 1. InternS2 / LMDeploy :23333
# --------------------------------------------------

echo "[1/4] Starting InternS2 inference..."

(
    export CUDA_VISIBLE_DEVICES="$INFERENCE_GPUS"
    export PATH="$INFERENCE_ENV/bin:$PATH"

    exec "$INFERENCE_ENV/bin/lmdeploy" serve api_server \
        "$MODEL_DIR" \
        --trust-remote-code \
        --backend pytorch \
        --tp "$INFERENCE_TP" \
        --server-port 23333 \
        --reasoning-parser default \
        --tool-call-parser interns2-preview
) >"$LOG_DIR/inference.log" 2>&1 &

INFERENCE_PID=$!
PIDS+=("$INFERENCE_PID")

echo "      PID=$INFERENCE_PID"
echo "      GPUs=$INFERENCE_GPUS"
echo "      TP=$INFERENCE_TP"
echo "      log=$LOG_DIR/inference.log"


# --------------------------------------------------
# 2. planner-adapter :8002
# --------------------------------------------------

echo "[2/4] Starting planner-adapter..."

(
    export PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT"

    export PLANNER_PROVIDER="${PLANNER_PROVIDER:-mock}"
    export PLANNER_MOCK_OUTCOME="${PLANNER_MOCK_OUTCOME:-success}"

    export PLANNER_ADAPTER_HOST=127.0.0.1
    export PLANNER_ADAPTER_PORT=8002
    export PLANNER_ADAPTER_LOG_LEVEL=info

    exec "$PLANNER_ENV/bin/python" \
        -m planner_adapter.main
) >"$LOG_DIR/planner-adapter.log" 2>&1 &

PLANNER_PID=$!
PIDS+=("$PLANNER_PID")

echo "      PID=$PLANNER_PID"
echo "      log=$LOG_DIR/planner-adapter.log"


# --------------------------------------------------
# 3. Xvfb + robot-simulation :8001
# --------------------------------------------------

echo "[3/4] Starting Xvfb + robot-simulation..."

(
    exec "$SIM_ENV/bin/Xvfb" ":$XVFB_DISPLAY" \
        -screen 0 1280x1024x24 \
        -nolisten tcp \
        -ac
) >"$LOG_DIR/xvfb.log" 2>&1 &

XVFB_PID=$!
PIDS+=("$XVFB_PID")

sleep 1

if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    echo "ERROR: Xvfb failed to start."
    tail -n 80 "$LOG_DIR/xvfb.log" || true
    exit 1
fi

(
    export SOFA_ROOT="$SOFA_ROOT"
    export SOFAPYTHON3_ROOT="$SOFAPYTHON3_ROOT"

    export PATH="$SOFA_ROOT/bin:$SIM_ENV/bin:$PATH"

    export PYTHONPATH="$SOFAPYTHON3_ROOT/lib/python3/site-packages:$APP_ROOT/third_party/sofa_env:$APP_ROOT/packages/surgical_contracts:$APP_ROOT"

    export LD_LIBRARY_PATH="$SIM_ENV/lib:$SOFA_ROOT/bin:$SOFA_ROOT/lib:$SOFAPYTHON3_ROOT/lib"

    export E05_MODEL_DIR="$E05_MODEL_DIR"

    export DISPLAY=":$XVFB_DISPLAY"
    export LIBGL_ALWAYS_SOFTWARE=1
    export LIBGL_DRIVERS_PATH="$SIM_ENV/lib/dri"
    export QT_QPA_PLATFORM=offscreen
    export OMP_NUM_THREADS=1

    export ROBOT_SIMULATION_HOST=127.0.0.1
    export ROBOT_SIMULATION_PORT=8001
    export ROBOT_SIMULATION_LOG_LEVEL=info

    exec "$SIM_ENV/bin/python" \
        -m simulation.server.main
) >"$LOG_DIR/robot-simulation.log" 2>&1 &

SIM_PID=$!
PIDS+=("$SIM_PID")

echo "      Xvfb PID=$XVFB_PID"
echo "      simulation PID=$SIM_PID"
echo "      DISPLAY=:$XVFB_DISPLAY"
echo "      log=$LOG_DIR/robot-simulation.log"


# --------------------------------------------------
# Wait for the three downstream services
# --------------------------------------------------

echo
echo "Checking downstream services..."

wait_http \
    "InternS2 inference" \
    "http://127.0.0.1:23333/v1/models" \
    300 \
    "$LOG_DIR/inference.log"

wait_http \
    "planner-adapter" \
    "http://127.0.0.1:8002/health" \
    30 \
    "$LOG_DIR/planner-adapter.log"

wait_http \
    "robot-simulation" \
    "http://127.0.0.1:8001/health" \
    120 \
    "$LOG_DIR/robot-simulation.log"


# --------------------------------------------------
# 4. agent-web :8000
# --------------------------------------------------

echo
echo "[4/4] Starting agent-web..."

(
    export PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT"

    export INTERNS2_BASE_URL=http://127.0.0.1:23333/v1
    export INTERNS2_API_KEY=EMPTY
    export INTERNS2_MODEL="$MODEL_DIR"
    export INTERNS2_TEMPERATURE=0

    export RUNTIME_MODE=simulation
    export DEFAULT_COORDINATE_FRAME=robot_base
    export DEFAULT_DISTANCE_UNIT=mm

    export ROBOT_SIMULATION_BASE_URL=http://127.0.0.1:8001
    export PLANNER_ADAPTER_BASE_URL=http://127.0.0.1:8002
    export PUNCTURE_EXECUTION_ENABLED=false

    export ASR_BACKEND=faster-whisper
    export ASR_MODEL_PATH="$APP_ROOT/models/asr/faster-whisper-small"
    export ASR_MODEL_NAME=faster-whisper-small
    export ASR_DEVICE=cpu
    export ASR_COMPUTE_TYPE=int8
    export ASR_LANGUAGE=zh
    export ASR_CPU_THREADS=4
    export ASR_MAX_DURATION_SECONDS=30
    export ASR_LOW_CONFIDENCE_THRESHOLD=0.65

    export GESTURE_MIN_CONFIDENCE=0.85
    export GESTURE_SAFETY_MIN_CONFIDENCE=0.80
    export GESTURE_STABLE_FRAMES=2
    export GESTURE_COOLDOWN_SECONDS=1.0
    export GESTURE_VOICE_CONFLICT_WINDOW_SECONDS=1.5

    export AGENT_WEB_HOST=127.0.0.1
    export AGENT_WEB_PORT=8000
    export AGENT_WEB_LOG_LEVEL=info

    exec "$AGENT_WEB_ENV/bin/python" \
        -m web.backend.main
) >"$LOG_DIR/agent-web.log" 2>&1 &

AGENT_PID=$!
PIDS+=("$AGENT_PID")

echo "      PID=$AGENT_PID"
echo "      log=$LOG_DIR/agent-web.log"

wait_http \
    "agent-web" \
    "http://127.0.0.1:8000/health" \
    60 \
    "$LOG_DIR/agent-web.log"


echo
echo "=================================================="
echo " ALL SERVICES HEALTHY"
echo "=================================================="
echo
echo " InternS2 inference : http://127.0.0.1:23333"
echo " robot-simulation   : http://127.0.0.1:8001"
echo " planner-adapter    : http://127.0.0.1:8002"
echo " agent-web          : http://127.0.0.1:8000"
echo
echo " Logs:"
echo "   $LOG_DIR/inference.log"
echo "   $LOG_DIR/robot-simulation.log"
echo "   $LOG_DIR/planner-adapter.log"
echo "   $LOG_DIR/agent-web.log"
echo
echo "Keep this terminal open."
echo "Press Ctrl+C to stop the whole system."
echo "=================================================="

# If any managed process dies unexpectedly, leave the supervisor and
# let the EXIT trap shut the rest down as well.
set +e
wait -n "${PIDS[@]}"
STATUS=$?
set -e

echo
echo "A managed process exited unexpectedly (status=$STATUS)."
exit "$STATUS"
