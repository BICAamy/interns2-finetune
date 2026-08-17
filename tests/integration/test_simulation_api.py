from __future__ import annotations

from dataclasses import dataclass, replace
from threading import get_ident
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from simulation.entry_point_env import ContinuousTrajectoryController, EntryPointEnvConfig
from simulation.server.api import create_app
from simulation.server.simulation_worker import SimulationWorker
from simulation.server.video_stream import encode_jpeg, mjpeg_chunk
from surgical_contracts import CommandExecutionStatus, MotionState


CONFIG = EntryPointEnvConfig.from_yaml()
TERMINAL = {
    CommandExecutionStatus.SUCCEEDED.value,
    CommandExecutionStatus.FAILED.value,
    CommandExecutionStatus.REJECTED.value,
    CommandExecutionStatus.CANCELLED.value,
}


@dataclass(frozen=True)
class FakeObservation:
    state: object
    joint_positions_deg: tuple[float, ...]
    rgb: np.ndarray


class ControllerEnvironment:
    """SOFA-free environment with the exact Step 5 motion semantics."""

    def __init__(self) -> None:
        self.config = CONFIG
        self.controller = ContinuousTrajectoryController(CONFIG)
        self.owner_thread_ids: set[int] = set()
        self.closed = False
        self._frame = np.zeros(CONFIG.image_shape + (3,), dtype=np.uint8)
        self._frame[10:30, 10:30] = (20, 180, 80)

    def _owned(self) -> None:
        self.owner_thread_ids.add(get_ident())

    def reset(self, seed=None, options=None):
        self._owned()
        state = self.controller.reset(seed=seed)
        return FakeObservation(
            state=state,
            joint_positions_deg=self.controller.joint_positions_deg,
            rgb=self._frame.copy(),
        )

    def move_to_entry(self, point, speed_mm_s=None):
        self._owned()
        return self.controller.move_to_entry(point, speed_mm_s)

    def move_relative(self, delta_mm, speed_mm_s=None):
        self._owned()
        return self.controller.move_relative(delta_mm, speed_mm_s)

    def step(self):
        self._owned()
        return replace(self.controller.step(), rgb=self._frame.copy())

    def get_state(self):
        self._owned()
        return self.controller.get_state()

    def stop(self):
        self._owned()
        return self.controller.stop()

    def emergency_stop(self):
        self._owned()
        return self.controller.emergency_stop()

    def close(self):
        self._owned()
        self.closed = True


@pytest.fixture
def service():
    environment = ControllerEnvironment()
    worker = SimulationWorker(
        lambda: environment,
        tick_interval_s=0.001,
        pause_on_no_clients=False,
    )
    with TestClient(create_app(worker)) as client:
        yield client, worker, environment


def wait_for_terminal(client: TestClient, command_id: str, timeout_s: float = 5.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/v1/commands/{command_id}")
        assert response.status_code == 200, response.text
        record = response.json()
        if record["status"] in TERMINAL:
            return record
        time.sleep(0.005)
    raise AssertionError(f"command {command_id} did not finish before timeout")


def point_payload(x: float, y: float, z: float):
    return {
        "x": x,
        "y": y,
        "z": z,
        "unit": "mm",
        "frame": "robot_base",
        "source": "structured_data",
    }


def test_health_state_and_single_environment_owner(service):
    client, _worker, environment = service
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert health.json()["worker_alive"] is True

    state = client.get("/v1/state")
    assert state.status_code == 200
    assert state.json()["state"]["mode"] == "simulation"
    assert state.json()["state"]["tcp"] == "needle_tip"
    assert len(state.json()["joint_positions_deg"]) == 6
    assert len(environment.owner_thread_ids) == 1


def test_move_to_entry_is_idempotent_and_conflicts_are_rejected(service):
    client, _worker, _environment = service
    request = {
        "command_id": "entry-api-001",
        "entry_point": point_payload(500.0, 0.0, 500.0),
        "speed_mm_s": 50.0,
    }
    first = client.post("/v1/commands/move-to-entry", json=request)
    second = client.post("/v1/commands/move-to-entry", json=request)
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["submitted_at_ms"] == second.json()["submitted_at_ms"]

    conflicting = client.post(
        "/v1/commands/move-to-entry",
        json={**request, "speed_mm_s": 25.0},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["code"] == "COMMAND_CONFLICT"

    result = wait_for_terminal(client, request["command_id"])
    assert result["status"] == "succeeded"
    assert result["result"]["reached"] is True
    assert result["result"]["position_error_mm"] <= CONFIG.reach_tolerance_mm


def test_normal_commands_are_serialized_and_telemetry_is_updated(service):
    client, _worker, _environment = service
    commands = (
        ("relative-api-001", [0.0, 0.0, 5.0]),
        ("relative-api-002", [0.0, 0.0, -5.0]),
    )
    for command_id, translation in commands:
        response = client.post(
            "/v1/commands/move-relative",
            json={
                "command_id": command_id,
                "translation_mm": translation,
                "frame": "robot_base",
                "speed_mm_s": 20.0,
            },
        )
        assert response.status_code == 202

    for command_id, _translation in commands:
        assert wait_for_terminal(client, command_id)["status"] == "succeeded"

    telemetry = client.get("/v1/state").json()
    assert telemetry["state"]["motion_state"] == "idle"
    assert telemetry["sequence"] > 1
    assert len(telemetry["trajectory_mm"]) > 2
    assert telemetry["frame_sequence"] > 0


def test_low_speed_relative_result_preserves_requested_eight_mm(service):
    client, _worker, _environment = service
    initial = client.get("/v1/state").json()["state"]["tcp_position"]
    response = client.post(
        "/v1/commands/move-relative",
        json={
            "command_id": "relative-api-exact-8mm",
            "translation_mm": [0.0, 0.0, 8.0],
            "frame": "robot_base",
            "speed_mm_s": 5.0,
        },
    )
    assert response.status_code == 202

    record = wait_for_terminal(client, "relative-api-exact-8mm")
    assert record["status"] == "succeeded"
    final = record["result"]["final_tcp_position"]
    assert float(final["x"]) == pytest.approx(float(initial["x"]), abs=0.05)
    assert float(final["y"]) == pytest.approx(float(initial["y"]), abs=0.05)
    assert float(final["z"]) - float(initial["z"]) == pytest.approx(8.0, abs=0.05)


def test_stop_preempts_active_motion(service):
    client, _worker, _environment = service
    moving = client.post(
        "/v1/commands/move-to-entry",
        json={
            "command_id": "long-entry-001",
            "entry_point": point_payload(600.0, 0.0, 500.0),
            "speed_mm_s": 1.0,
        },
    )
    assert moving.status_code == 202

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if client.get("/v1/commands/long-entry-001").json()["status"] == "running":
            break
        time.sleep(0.005)
    else:
        raise AssertionError("long motion never entered running state")

    stop = client.post("/v1/commands/stop", json={"command_id": "stop-api-001"})
    assert stop.status_code == 202
    assert wait_for_terminal(client, "stop-api-001")["status"] == "succeeded"
    assert wait_for_terminal(client, "long-entry-001")["status"] == "cancelled"
    assert client.get("/v1/state").json()["state"]["motion_state"] == "stopped"


def test_stop_cancels_motion_that_is_still_queued(service):
    client, _worker, _environment = service
    move = client.post(
        "/v1/commands/move-to-entry",
        json={
            "command_id": "queued-entry-001",
            "entry_point": point_payload(600.0, 0.0, 500.0),
            "speed_mm_s": 1.0,
        },
    )
    stop = client.post("/v1/commands/stop", json={"command_id": "queued-stop-001"})
    assert move.status_code == 202
    assert stop.status_code == 202
    assert wait_for_terminal(client, "queued-stop-001")["status"] == "succeeded"
    move_result = wait_for_terminal(client, "queued-entry-001")
    assert move_result["status"] == "cancelled"


def test_estop_blocks_motion_until_reset(service):
    client, _worker, _environment = service
    client.post("/v1/commands/estop", json={"command_id": "estop-api-001"})
    assert wait_for_terminal(client, "estop-api-001")["status"] == "succeeded"
    state = client.get("/v1/state").json()["state"]
    assert state["estop"] is True
    assert state["motion_state"] == "estop"

    rejected = client.post(
        "/v1/commands/move-relative",
        json={
            "command_id": "blocked-relative-001",
            "translation_mm": [0.0, 0.0, 5.0],
        },
    )
    assert rejected.status_code == 202
    blocked = wait_for_terminal(client, "blocked-relative-001")
    assert blocked["status"] == "rejected"
    assert blocked["error"]["code"] == "ESTOP_ACTIVE"

    client.post("/v1/reset", json={"command_id": "reset-api-001", "seed": 7})
    assert wait_for_terminal(client, "reset-api-001")["status"] == "succeeded"
    assert client.get("/v1/state").json()["state"]["estop"] is False


def test_validation_unknown_command_events_and_jpeg(service):
    client, _worker, _environment = service
    invalid = client.post(
        "/v1/commands/move-relative",
        json={"command_id": "bad", "translation_mm": [0.0, 0.0]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_COMMAND_SCHEMA"

    missing = client.get("/v1/commands/does-not-exist")
    assert missing.status_code == 404

    with client.websocket_connect("/v1/events?after=0") as websocket:
        event = websocket.receive_json()
        assert event["sequence"] >= 1
        assert event["event_type"] in {"state_updated", "worker_ready"}

    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    frame[5:10, 5:10] = (255, 0, 0)
    jpeg = encode_jpeg(frame)
    assert jpeg.startswith(b"\xff\xd8") and jpeg.endswith(b"\xff\xd9")
    chunk = mjpeg_chunk(jpeg)
    assert b"Content-Type: image/jpeg" in chunk
    assert jpeg in chunk


def test_unsupported_tcp_orientation_and_frame_are_rejected(service):
    client, _worker, _environment = service
    wrong_tcp = client.post(
        "/v1/commands/move-to-entry",
        json={
            "command_id": "wrong-tcp-001",
            "entry_point": point_payload(500.0, 0.0, 500.0),
            "tcp": "flange",
        },
    )
    assert wrong_tcp.status_code == 202
    assert wait_for_terminal(client, "wrong-tcp-001")["status"] == "rejected"

    wrong_orientation = client.post(
        "/v1/commands/move-to-entry",
        json={
            "command_id": "wrong-orientation-001",
            "entry_point": point_payload(500.0, 0.0, 500.0),
            "orientation_policy": "point_towards_target",
        },
    )
    assert wrong_orientation.status_code == 202
    assert wait_for_terminal(client, "wrong-orientation-001")["status"] == "rejected"

    wrong_frame = client.post(
        "/v1/commands/move-relative",
        json={
            "command_id": "wrong-frame-001",
            "translation_mm": [0.0, 0.0, 5.0],
            "frame": "simulation_world",
        },
    )
    assert wrong_frame.status_code == 202
    result = wait_for_terminal(client, "wrong-frame-001")
    assert result["status"] == "rejected"
    assert result["error"]["code"] == "INVALID_COMMAND_SCHEMA"


def test_pause_on_disconnect_is_configurable():
    environment = ControllerEnvironment()
    worker = SimulationWorker(
        lambda: environment,
        tick_interval_s=0.001,
        pause_on_no_clients=True,
    )
    worker.start()
    try:
        from surgical_contracts import MoveRelativeRequest, RobotCommandKind

        worker.submit(
            RobotCommandKind.MOVE_RELATIVE,
            MoveRelativeRequest(
                command_id="paused-relative-001",
                translation_mm=(0.0, 0.0, 5.0),
                speed_mm_s=20.0,
            ),
        )
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            record = worker.get_command("paused-relative-001")
            if record.status == CommandExecutionStatus.RUNNING:
                break
            time.sleep(0.005)
        else:
            raise AssertionError("paused command never entered running state")

        before = worker.get_state().tcp_position
        time.sleep(0.03)
        assert worker.get_state().tcp_position == before

        worker.register_client()
        result = worker.wait_for_command("paused-relative-001", timeout_s=2.0)
        worker.unregister_client()
        assert result.status == CommandExecutionStatus.SUCCEEDED
    finally:
        worker.shutdown()
