"""End-to-end HTTP/MJPEG acceptance check for a running Step 6 service."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


TERMINAL = {"succeeded", "failed", "rejected", "cancelled"}


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            return json.load(response)
    except HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {error.code}: {message}") from error


def wait_for_command(
    base_url: str,
    command_id: str,
    *,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        record = request_json(base_url, f"/v1/commands/{command_id}")
        if record["status"] in TERMINAL:
            if record["status"] != "succeeded":
                raise RuntimeError(f"command failed: {record}")
            return record
        time.sleep(0.1)
    raise TimeoutError(f"command {command_id} did not complete in {timeout_s}s")


def check_mjpeg(base_url: str, *, timeout_s: float) -> dict[str, Any]:
    with urlopen(f"{base_url.rstrip('/')}/v1/stream.mjpeg", timeout=timeout_s) as response:
        content_type = response.headers.get("Content-Type", "")
        if "multipart/x-mixed-replace" not in content_type:
            raise RuntimeError(f"unexpected stream content type: {content_type}")
        boundary = response.readline().strip()
        headers: dict[str, str] = {}
        while True:
            line = response.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
            name, value = line.decode("ascii").split(":", 1)
            headers[name.lower()] = value.strip()
        length = int(headers["content-length"])
        jpeg = response.read(length)
    if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
        raise RuntimeError("MJPEG stream did not contain a complete JPEG frame")
    return {"boundary": boundary.decode("ascii"), "jpeg_bytes": len(jpeg)}


def run_check(base_url: str, *, timeout_s: float) -> dict[str, Any]:
    health = request_json(base_url, "/health")
    if health.get("status") != "healthy" or not health.get("ready"):
        raise RuntimeError(f"service is not healthy: {health}")

    suffix = str(time.time_ns())
    reset_id = f"accept-reset-{suffix}"
    entry_id = f"accept-entry-{suffix}"
    relative_id = f"accept-relative-{suffix}"

    request_json(
        base_url,
        "/v1/reset",
        method="POST",
        payload={"command_id": reset_id, "seed": 2026},
    )
    wait_for_command(base_url, reset_id, timeout_s=timeout_s)

    request_json(
        base_url,
        "/v1/commands/move-to-entry",
        method="POST",
        payload={
            "command_id": entry_id,
            "entry_point": {
                "x": 500.0,
                "y": 0.0,
                "z": 500.0,
                "unit": "mm",
                "frame": "robot_base",
            },
            "speed_mm_s": 50.0,
        },
    )
    entry = wait_for_command(base_url, entry_id, timeout_s=timeout_s)

    request_json(
        base_url,
        "/v1/commands/move-relative",
        method="POST",
        payload={
            "command_id": relative_id,
            "translation_mm": [0.0, 0.0, 5.0],
            "frame": "robot_base",
            "speed_mm_s": 20.0,
        },
    )
    relative = wait_for_command(base_url, relative_id, timeout_s=timeout_s)
    telemetry = request_json(base_url, "/v1/state")
    position = telemetry["state"]["tcp_position"]
    expected = (500.0, 0.0, 505.0)
    actual = (float(position["x"]), float(position["y"]), float(position["z"]))
    if any(abs(value - target) > 0.5 for value, target in zip(actual, expected)):
        raise RuntimeError(f"unexpected final TCP position: {actual}")

    return {
        "status": "ok",
        "service": "robot-simulation",
        "health": health,
        "entry_command": entry,
        "relative_command": relative,
        "final_tcp_position_mm": actual,
        "telemetry_sequence": telemetry["sequence"],
        "trajectory_points": len(telemetry["trajectory_mm"]),
        "mjpeg": check_mjpeg(base_url, timeout_s=timeout_s),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    result = run_check(args.base_url, timeout_s=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

