#!/usr/bin/env bash
set -u

check() {
    local name="$1"
    local url="$2"
    local port="$3"

    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
        printf "%-22s RUNNING   :%-5s  HEALTHY\n" "$name" "$port"
    else
        printf "%-22s DOWN      :%-5s  UNAVAILABLE\n" "$name" "$port"
    fi
}

echo "=================================================="
echo " Surgical Navigation Service Status"
echo "=================================================="

check "interns2-inference" \
    "http://127.0.0.1:23333/v1/models" \
    "23333"

check "robot-simulation" \
    "http://127.0.0.1:8001/health" \
    "8001"

check "planner-adapter" \
    "http://127.0.0.1:8002/health" \
    "8002"

check "agent-web" \
    "http://127.0.0.1:8000/health" \
    "8000"

echo "=================================================="
