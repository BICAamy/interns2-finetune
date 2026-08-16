"""Docker healthcheck for the local robot-simulation process."""

from __future__ import annotations

import json
import os
from urllib.request import urlopen


def main() -> int:
    port = int(os.environ.get("ROBOT_SIMULATION_PORT", "8001"))
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=3.0) as response:
        status = response.status
        payload = json.load(response)
    if status != 200 or payload.get("status") != "healthy":
        raise RuntimeError(f"robot-simulation is not healthy: {payload}")
    if not payload.get("worker_alive") or not payload.get("ready"):
        raise RuntimeError(f"simulation worker is not ready: {payload}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
