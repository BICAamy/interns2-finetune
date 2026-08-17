"""Container healthcheck for planner-adapter."""

from __future__ import annotations

import json
import os
from urllib.request import urlopen


def main() -> None:
    port = int(os.getenv("PLANNER_ADAPTER_PORT", "8002"))
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=3.0) as response:
        payload = json.load(response)
        status = response.status
    if status != 200 or not payload.get("ready"):
        raise RuntimeError(f"planner-adapter is not ready: {payload}")


if __name__ == "__main__":
    main()
