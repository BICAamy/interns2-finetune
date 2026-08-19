#!/usr/bin/env bash
set -Eeuo pipefail

FAILED=0

check() {
    local name="$1"
    local url="$2"

    echo
    echo "--------------------------------------------------"
    echo "$name"
    echo "$url"
    echo "--------------------------------------------------"

    if response=$(curl -fsS --max-time 5 "$url"); then
        echo "$response"

        if printf '%s' "$response" | python3 -m json.tool >/dev/null 2>&1; then
            echo
            echo "[PASS] HTTP OK + valid JSON"
        else
            echo
            echo "[FAIL] Response is not valid JSON"
            FAILED=1
        fi
    else
        echo "[FAIL] Service unavailable"
        FAILED=1
    fi
}

echo "=================================================="
echo " Surgical Navigation Health Check"
echo "=================================================="

check \
    "InternS2 inference" \
    "http://127.0.0.1:23333/v1/models"

check \
    "robot-simulation" \
    "http://127.0.0.1:8001/health"

check \
    "planner-adapter" \
    "http://127.0.0.1:8002/health"

check \
    "agent-web" \
    "http://127.0.0.1:8000/health"

echo
echo "=================================================="

if (( FAILED == 0 )); then
    echo " ALL HEALTH CHECKS PASSED"
    echo "=================================================="
    exit 0
else
    echo " HEALTH CHECK FAILED"
    echo "=================================================="
    exit 1
fi
