"""End-to-end HTTP smoke check for the Step 9 mock adapter."""

from __future__ import annotations

import argparse
import json
from urllib.request import Request, urlopen

from surgical_contracts import PlannerHealth, PlannerStatus, PlanPunctureResult


def request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"} if body else {},
        method="POST" if body else "GET",
    )
    with urlopen(request, timeout=10.0) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    args = parser.parse_args()

    health = PlannerHealth.model_validate(request_json(args.base_url, "/health"))
    if not health.ready or health.provider != "mock":
        raise RuntimeError(f"planner-adapter is not ready in mock mode: {health}")

    result = PlanPunctureResult.model_validate(
        request_json(
            args.base_url,
            "/v1/plan",
            {
                "schema_version": "1.0",
                "request_id": "step9-smoke-plan",
                "command_id": "step9-smoke-command",
                "entry_point": {
                    "x": 20.0,
                    "y": 35.0,
                    "z": 80.0,
                    "unit": "mm",
                    "frame": "robot_base",
                    "source": "structured_data",
                },
                "target_point": {
                    "x": 24.0,
                    "y": 38.0,
                    "z": 120.0,
                    "unit": "mm",
                    "frame": "robot_base",
                    "source": "structured_data",
                },
            },
        )
    )
    if result.status != PlannerStatus.SUCCESS:
        raise RuntimeError(f"mock planning did not succeed: {result}")
    if result.executable or result.control_mode != "mock_preview":
        raise RuntimeError(f"mock safety boundary was violated: {result}")

    print(
        json.dumps(
            {
                "status": "ok",
                "health": health.model_dump(mode="json"),
                "planning_result": result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
