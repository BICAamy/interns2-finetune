#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/UNICOMFS/shskw43_1/.bihu/interns2-agent-robot/interns2-finetune"
LOG_DIR="$ROOT/logs/services"

INFERENCE_ENV="/UNICOMFS/shskw43_1/.venvs/interns2"
PLANNER_ENV="/UNICOMFS/shskw43_1/.venvs/planner-adapter"
SIM_ENV="/UNICOMFS/shskw43_1/.micromamba/envs/interns2-simulation"
AGENT_WEB_ENV="/UNICOMFS/shskw43_1/.micromamba/envs/interns2-agent-web"

SOFA_ROOT="/UNICOMFS/shskw43_1/software/sofa-install/SOFA_v24.06.00_Linux"
SOFAPYTHON3_ROOT="$SOFA_ROOT/plugins/SofaPython3"
E05_MODEL_DIR="/UNICOMFS/shskw43_1/software/huayan-elfin-model/model/485/elfin5"

mkdir -p "$LOG_DIR"
cd "$ROOT"

PIDS=()

cleanup() {
    trap - INT TERM EXIT

    echo
    echo "Stopping surgical-navigation services..."

    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done

    sleep 1

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done

    wait 2>/dev/null || true

    echo "All services stopped."
}

trap cleanup INT TERM EXIT


wait_http() {
    local name="$1"
    local url="$2"
    local timeout_s="$3"
    local log_file="$4"

    local deadline=$((SECONDS + timeout_s))

    printf "Waiting for %-20s " "$name"

    while (( SECONDS < deadline )); do
        if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
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
echo " InternS2 Surgical Navigation - Step 15"
echo "=================================================="
echo


# --------------------------------------------------
# 1. InternS2 / LMDeploy :23333
# --------------------------------------------------

echo "[1/4] Starting InternS2 inference..."

(
    export CUDA_VISIBLE_DEVICES=0,1

    exec "$INFERENCE_ENV/bin/lmdeploy" serve api_server \
        "$ROOT/models/Intern-S2-Preview" \
        --trust-remote-code \
        --backend pytorch \
        --tp 2 \
        --server-port 23333 \
        --reasoning-parser default \
        --tool-call-parser interns2-preview
) >"$LOG_DIR/inference.log" 2>&1 &

INFERENCE_PID=$!
PIDS+=("$INFERENCE_PID")

echo "      PID=$INFERENCE_PID"
echo "      log=$LOG_DIR/inference.log"


# --------------------------------------------------
# 2. planner-adapter :8002
# --------------------------------------------------

echo "[2/4] Starting planner-adapter..."

(
    export PYTHONPATH="$ROOT/packages/surgical_contracts:$ROOT"

    export PLANNER_PROVIDER=mock
    export PLANNER_MOCK_OUTCOME=success

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
    exec "$SIM_ENV/bin/Xvfb" :99 \
        -screen 0 1280x1024x24 \
        -nolisten tcp \
        -ac
) >"$LOG_DIR/xvfb.log" 2>&1 &

XVFB_PID=$!
PIDS+=("$XVFB_PID")

sleep 1

(
    export SOFA_ROOT="$SOFA_ROOT"
    export SOFAPYTHON3_ROOT="$SOFAPYTHON3_ROOT"

    export PATH="$SOFA_ROOT/bin:$SIM_ENV/bin:$PATH"

    export PYTHONPATH="$SOFAPYTHON3_ROOT/lib/python3/site-packages:$ROOT/third_party/sofa_env:$ROOT/packages/surgical_contracts:$ROOT"

    export LD_LIBRARY_PATH="$SIM_ENV/lib:$SOFA_ROOT/bin:$SOFA_ROOT/lib:$SOFAPYTHON3_ROOT/lib"

    export E05_MODEL_DIR="$E05_MODEL_DIR"

    export DISPLAY=:99
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
    export PYTHONPATH="$ROOT/packages/surgical_contracts:$ROOT"

    export INTERNS2_BASE_URL=http://127.0.0.1:23333/v1
    export INTERNS2_API_KEY=EMPTY
    export INTERNS2_MODEL="$ROOT/models/Intern-S2-Preview"
    export INTERNS2_TEMPERATURE=0

    export RUNTIME_MODE=simulation
    export DEFAULT_COORDINATE_FRAME=robot_base
    export DEFAULT_DISTANCE_UNIT=mm

    export ROBOT_SIMULATION_BASE_URL=http://127.0.0.1:8001
    export PLANNER_ADAPTER_BASE_URL=http://127.0.0.1:8002
    export PUNCTURE_EXECUTION_ENABLED=false

    export ASR_BACKEND=faster-whisper
    export ASR_MODEL_PATH="$ROOT/models/asr/faster-whisper-small"
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
