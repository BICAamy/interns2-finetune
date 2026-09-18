#!/usr/bin/env bash
set -Eeuo pipefail

if command -v pgrep >/dev/null 2>&1; then
    pgrep -fl '[p]ython.*-m edge_gateway.main' || {
        echo 'edge gateway: not running'
        exit 1
    }
else
    echo 'pgrep is unavailable; check the gateway terminal and audit log.'
    exit 1
fi
