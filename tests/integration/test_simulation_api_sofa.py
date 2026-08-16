from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from simulation.server.api import create_app
from simulation.server.video_stream import encode_jpeg


RUN_SOFA_SERVICE_TEST = os.environ.get("ROBOT_SIMULATION_SOFA_TESTS") == "1"


def wait_for_success(client: TestClient, command_id: str, timeout_s: float = 15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/v1/commands/{command_id}")
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] == "succeeded":
            return record
        if record["status"] in {"failed", "rejected", "cancelled"}:
            raise AssertionError(record)
        time.sleep(0.05)
    raise AssertionError(f"command {command_id} did not complete before timeout")


@pytest.mark.skipif(
    not RUN_SOFA_SERVICE_TEST,
    reason="set ROBOT_SIMULATION_SOFA_TESTS=1 inside the Xvfb simulation image",
)
def test_real_sofa_worker_through_http_and_rgb_frame():
    if not os.environ.get("DISPLAY"):
        pytest.fail("real service test must run through run-with-xvfb")

    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        move = client.post(
            "/v1/commands/move-to-entry",
            json={
                "command_id": "sofa-http-entry-001",
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
        assert move.status_code == 202
        entry = wait_for_success(client, "sofa-http-entry-001")
        assert entry["result"]["reached"] is True

        relative = client.post(
            "/v1/commands/move-relative",
            json={
                "command_id": "sofa-http-relative-001",
                "translation_mm": [0.0, 0.0, 5.0],
                "frame": "robot_base",
                "speed_mm_s": 20.0,
            },
        )
        assert relative.status_code == 202
        wait_for_success(client, "sofa-http-relative-001")

        telemetry = client.get("/v1/state").json()
        position = telemetry["state"]["tcp_position"]
        assert abs(position["x"] - 500.0) <= 0.5
        assert abs(position["y"]) <= 0.5
        assert abs(position["z"] - 505.0) <= 0.5
        assert telemetry["frame_sequence"] > 0

        worker = client.app.state.simulation_worker
        _sequence, frame = worker.wait_for_frame(-1, timeout_s=2.0)
        assert frame is not None
        jpeg = encode_jpeg(frame)
        assert jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")
