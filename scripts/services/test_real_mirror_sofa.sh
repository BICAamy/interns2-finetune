#!/usr/bin/env bash
# Offline SOFA/Xvfb verification for Step 7; never connects to the controller.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
APP_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd -P)"
BUNDLE_ROOT="$(cd "$APP_ROOT/.." && pwd -P)"
SIM_ENV="$BUNDLE_ROOT/runtime/envs/simulation"
SOFA_ROOT="$BUNDLE_ROOT/software/SOFA_v24.06.00_Linux"
SOFAPYTHON3_ROOT="$SOFA_ROOT/plugins/SofaPython3"
E05_MODEL_DIR="$BUNDLE_ROOT/software/huayan-elfin-model/model/485/elfin5"

test -x "$SIM_ENV/bin/python"
test -x "$SIM_ENV/bin/Xvfb"
test -x "$SOFA_ROOT/bin/runSofa"
test -d "$SOFAPYTHON3_ROOT"
test -d "$E05_MODEL_DIR"

cd "$APP_ROOT"
export SOFA_ROOT SOFAPYTHON3_ROOT
export PATH="$SOFA_ROOT/bin:$SIM_ENV/bin:$PATH"
export PYTHONPATH="$SOFAPYTHON3_ROOT/lib/python3/site-packages:$APP_ROOT/third_party/sofa_env:$APP_ROOT/packages/surgical_contracts:$APP_ROOT"
export LD_LIBRARY_PATH="$SIM_ENV/lib:$SOFA_ROOT/bin:$SOFA_ROOT/lib:$SOFAPYTHON3_ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export E05_MODEL_DIR
export XVFB_DISPLAY_NUMBER="${XVFB_DISPLAY_NUMBER:-101}"
mkdir -p "$APP_ROOT/logs/services"
export XVFB_LOG_FILE="$APP_ROOT/logs/services/xvfb-real-mirror-test.log"
export LIBGL_ALWAYS_SOFTWARE=1
export LIBGL_DRIVERS_PATH="$SIM_ENV/lib/dri"
export QT_QPA_PLATFORM=offscreen
export OMP_NUM_THREADS=1
export ENTRY_POINT_SOFA_TESTS=1
export ROBOT_SIMULATION_SOFA_TESTS=1

exec sh "$APP_ROOT/simulation/scripts/run_with_xvfb.sh" \
    "$SIM_ENV/bin/python" -m pytest \
    tests/simulation/test_external_joint_state.py \
    tests/integration/test_simulation_api_sofa.py -q
