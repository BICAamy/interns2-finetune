"""Container health check using only the Python standard library."""

import json
import os
from urllib.request import urlopen


port = int(os.getenv("AGENT_WEB_PORT", "8000"))
with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
    payload = json.load(response)
if payload.get("status") != "healthy":
    raise SystemExit(1)
