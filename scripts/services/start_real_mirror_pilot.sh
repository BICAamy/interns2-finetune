#!/usr/bin/env bash
# Run only the authenticated, observe-only real runtime + passive SOFA mirror.
# This pilot uses :18011 and a separate Xvfb display; it does not restart the
# existing four-service simulation stack or send controller commands.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
SIM_ENV="$BUNDLE_ROOT/runtime/envs/simulation"
SOFA_ROOT="$BUNDLE_ROOT/software/SOFA_v24.06.00_Linux"
SOFAPYTHON3_ROOT="$SOFA_ROOT/plugins/SofaPython3"
E05_MODEL_DIR="$BUNDLE_ROOT/software/huayan-elfin-model/model/485/elfin5"

if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != --check-config ]]; }; then
    echo "Usage: $0 [--check-config]" >&2
    exit 2
fi

cd "$APP_ROOT"
REAL_CONFIG_PATH="${REAL_CONFIG_PATH:-$APP_ROOT/configs/robot-real.local.yaml}"
GATEWAY_AUTH_SECRET_FILE="${GATEWAY_AUTH_SECRET_FILE:-$APP_ROOT/configs/gateway-auth.local}"
: "${GATEWAY_EXPECTED_ID:?Set GATEWAY_EXPECTED_ID to the same ID used by the Mac gateway}"
export REAL_CONFIG_PATH GATEWAY_AUTH_SECRET_FILE GATEWAY_EXPECTED_ID

test -x "$SIM_ENV/bin/python"
test -f "$REAL_CONFIG_PATH"
test -f "$GATEWAY_AUTH_SECRET_FILE"
REAL_CONFIG_SHA256="$(PYTHONPATH="$APP_ROOT/packages/surgical_contracts:$APP_ROOT" \
    "$SIM_ENV/bin/python" -c '
from robot_runtime.real_config import load_real_config
from surgical_contracts import load_gateway_secret
import os
config = load_real_config(os.environ["REAL_CONFIG_PATH"])
if config.allowed_control != "observe-only":
    raise ValueError("pilot must remain observe-only")
load_gateway_secret(os.environ["GATEWAY_AUTH_SECRET_FILE"])
print(config.digest())
')"
export REAL_CONFIG_SHA256

if [[ "${1:-}" == --check-config ]]; then
    echo "REAL MIRROR PILOT CONFIG OK; REAL_CONFIG_SHA256=$REAL_CONFIG_SHA256"
    exit 0
fi

test -x "$SIM_ENV/bin/Xvfb"
test -x "$SOFA_ROOT/bin/runSofa"
test -d "$SOFAPYTHON3_ROOT"
test -d "$E05_MODEL_DIR"

export ROBOT_MODE=real RUNTIME_MODE=real ROBOT_CONTROL_MODE=observe-only
export ROBOT_REAL_MIRROR=1
export ROBOT_SIMULATION_HOST=127.0.0.1
export ROBOT_SIMULATION_PORT="${ROBOT_SIMULATION_PORT:-18011}"
export XVFB_DISPLAY_NUMBER="${XVFB_DISPLAY_NUMBER:-100}"
mkdir -p "$APP_ROOT/logs/services"
export XVFB_LOG_FILE="$APP_ROOT/logs/services/xvfb-real-mirror-pilot.log"
export SOFA_ROOT SOFAPYTHON3_ROOT E05_MODEL_DIR
export PATH="$SOFA_ROOT/bin:$SIM_ENV/bin:$PATH"
export PYTHONPATH="$SOFAPYTHON3_ROOT/lib/python3/site-packages:$APP_ROOT/third_party/sofa_env:$APP_ROOT/packages/surgical_contracts:$APP_ROOT"
export LD_LIBRARY_PATH="$SIM_ENV/lib:$SOFA_ROOT/bin:$SOFA_ROOT/lib:$SOFAPYTHON3_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export LIBGL_ALWAYS_SOFTWARE=1
export LIBGL_DRIVERS_PATH="$SIM_ENV/lib/dri"
export QT_QPA_PLATFORM=offscreen
export OMP_NUM_THREADS=1

exec sh "$APP_ROOT/simulation/scripts/run_with_xvfb.sh" \
    "$SIM_ENV/bin/python" -m robot_runtime.main
