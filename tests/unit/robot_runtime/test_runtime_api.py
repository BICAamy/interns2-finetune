from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent.tools.robot import (
    RobotRuntimeClientError,
    RobotRuntimeHTTPController,
    RobotRuntimeUnavailableError,
    RobotSimulationHTTPController,
)
from robot_runtime.api import create_app
from robot_runtime.providers import SimulationProvider
from simulation.server.video_stream import mjpeg_chunk
from surgical_contracts import (
    CommandExecutionStatus,
    MoveRelativeRequest,
    Point3D,
    RobotCommandKind,
    RobotCommandRecord,
    RobotState,
    SimulationCameraState,
    SimulationHealth,
    SimulationTelemetry,
)


class StubSimulationWorker:
    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.records: dict[str, RobotCommandRecord] = {}

    def start(self) -> None:
        self.started = True

    def shutdown(self) -> None:
        self.closed = True

    def health(self) -> SimulationHealth:
        return SimulationHealth(
            status="healthy",
            worker_alive=True,
            initialized=True,
            ready=True,
            queue_depth=0,
        )

    def get_telemetry(self) -> SimulationTelemetry:
        return SimulationTelemetry(
            state=RobotState(tcp_position=Point3D(x=500, y=0, z=500)),
            sequence=1,
            joint_positions_deg=(0, 0, 60, 0, 90, 0),
            trajectory_mm=[(500, 0, 500)],
            frame_sequence=1,
            updated_at_ms=1,
        )

    def get_camera_state(self) -> SimulationCameraState:
        return SimulationCameraState(
            preset="front",
            yaw_deg=0,
            pitch_deg=0,
            distance_m=1.65,
            target_m=(0.35, 0, 0.42),
            position_m=(0.35, -1.65, 0.42),
            updated_at_ms=1,
        )

    def control_camera(self, _request) -> SimulationCameraState:
        return self.get_camera_state()

    def submit(self, kind, request):
        now = time.time_ns() // 1_000_000
        record = RobotCommandRecord(
            command_id=request.command_id,
            kind=kind,
            status=CommandExecutionStatus.QUEUED,
            submitted_at_ms=now,
            updated_at_ms=now,
            request=request.model_dump(mode="json"),
        )
        self.records[record.command_id] = record
        return record, True

    def get_command(self, command_id: str) -> RobotCommandRecord:
        return self.records[command_id]

    def register_client(self) -> None:
        pass

    def unregister_client(self) -> None:
        pass

    def wait_for_events(self, after_sequence: int, *, timeout_s: float = 5.0):
        return []

    def wait_for_frame(self, after_sequence: int, *, timeout_s: float = 2.0):
        return 1, None


def test_simulation_provider_preserves_legacy_routes_and_mjpeg(monkeypatch) -> None:
    worker = StubSimulationWorker()
    monkeypatch.setattr(
        "robot_runtime.api.mjpeg_stream",
        lambda _provider: iter([mjpeg_chunk(b"\xff\xd8\xff\xd9")]),
    )
    app = create_app(provider=SimulationProvider(worker))
    assert app.state.simulation_worker is worker
    with TestClient(app) as client:
        assert worker.started
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["service"] == "robot-simulation"
        state = client.get("/v1/state")
        assert state.json()["state"]["mode"] == "simulation"
        assert client.get("/v1/camera").status_code == 200
        assert client.put("/v1/camera", json={"action": "preset", "preset": "front"}).status_code == 200
        request = {"command_id": "sim-stub-1", "translation_mm": [0, 0, 5]}
        response = client.post("/v1/commands/move-relative", json=request)
        assert response.status_code == 202
        assert response.json()["kind"] == RobotCommandKind.MOVE_RELATIVE.value
        assert client.get("/v1/commands/sim-stub-1").json() == response.json()
        stream = client.get("/v1/stream.mjpeg")
        assert stream.status_code == 200
        assert b"Content-Type: image/jpeg" in stream.content
    assert worker.closed


def test_real_stub_is_disconnected_and_rejects_every_command() -> None:
    with TestClient(create_app(mode="real")) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["runtime_mode"] == "real"
        assert health.json()["control_mode"] == "observe-only"
        assert health.json()["status"] == "degraded"
        assert health.json()["error"] == "gateway_disconnected"
        assert health.json()["ready_for_motion"] is False
        state = client.get("/v1/state")
        assert state.status_code == 200
        assert state.json()["freshness"] == "disconnected"
        assert state.json()["joint_positions_deg"] is None
        assert state.json()["actual_pose_robot_base"] is None

        commands = (
            ("/v1/reset", {"command_id": "real-reset"}),
            (
                "/v1/commands/move-to-entry",
                {"command_id": "real-entry", "entry_point": {"x": 500, "y": 0, "z": 500}},
            ),
            (
                "/v1/commands/move-relative",
                {"command_id": "real-relative", "translation_mm": [0, 0, 1]},
            ),
            ("/v1/commands/stop", {"command_id": "real-stop"}),
            ("/v1/commands/estop", {"command_id": "real-estop"}),
        )
        for path, payload in commands:
            response = client.post(path, json=payload)
            assert response.status_code == 403
            assert response.json()["code"] == "OPERATION_NOT_ENABLED"
            assert response.json()["command_id"] == payload["command_id"]
            record = client.get(f"/v1/commands/{payload['command_id']}")
            assert record.status_code == 200
            assert record.json()["status"] == "rejected"
            assert record.json()["error"]["code"] == "OPERATION_NOT_ENABLED"

        first_timestamp = client.get("/v1/commands/real-relative").json()["submitted_at_ms"]
        duplicate = client.post(commands[2][0], json=commands[2][1])
        assert duplicate.status_code == 403
        assert first_timestamp == client.get(
            "/v1/commands/real-relative"
        ).json()["submitted_at_ms"]
        conflict = client.post(
            commands[2][0],
            json={"command_id": "real-relative", "translation_mm": [0, 0, 2]},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "COMMAND_CONFLICT"
        missing = client.get("/v1/commands/unknown")
        assert missing.status_code == 404
        assert missing.json()["code"] == "COMMAND_NOT_FOUND"
        invalid = client.post(
            "/v1/commands/move-relative",
            json={"command_id": "bad", "translation_mm": [0, 0]},
        )
        assert invalid.status_code == 422

        for path in ("/v1/camera", "/v1/stream.mjpeg"):
            unavailable = client.get(path)
            assert unavailable.status_code == 503
            assert unavailable.json()["code"] == "OPERATION_NOT_ENABLED"
        unavailable_camera_update = client.put(
            "/v1/camera", json={"action": "preset", "preset": "front"}
        )
        assert unavailable_camera_update.status_code == 503
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/v1/events") as websocket:
                websocket.receive_json()
        assert exc.value.code == 1013


def test_generic_http_controller_keeps_old_name_and_reads_real_status() -> None:
    assert RobotRuntimeHTTPController is RobotSimulationHTTPController

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            from robot_runtime.providers import HuayanRealStubProvider

            return httpx.Response(200, json=HuayanRealStubProvider().health().model_dump(mode="json"))
        if request.url.path == "/v1/state":
            from robot_runtime.providers import HuayanRealStubProvider

            return httpx.Response(
                200,
                json=HuayanRealStubProvider().get_telemetry().model_dump(mode="json"),
            )
        if request.url.path == "/v1/commands/move-relative":
            return httpx.Response(
                403,
                json={
                    "schema_version": "1.0",
                    "code": "OPERATION_NOT_ENABLED",
                    "message": "Real robot control is disabled",
                    "command_id": "real-motion-blocked",
                    "request_id": None,
                    "details": {},
                },
            )
        raise AssertionError(request.url.path)

    client = httpx.Client(base_url="http://robot.test", transport=httpx.MockTransport(handler))
    robot = RobotRuntimeHTTPController("http://robot.test", client=client)
    assert robot.get_runtime_health().control_mode == "observe-only"
    assert robot.get_telemetry().runtime_mode.value == "real"
    with pytest.raises(RobotRuntimeUnavailableError):
        robot.health()
    with pytest.raises(RobotRuntimeUnavailableError):
        robot.get_state()
    with pytest.raises(RobotRuntimeClientError) as exc:
        robot.move_relative(
            MoveRelativeRequest(
                command_id="real-motion-blocked", translation_mm=(0, 0, 1)
            )
        )
    assert exc.value.error_code.value == "OPERATION_NOT_ENABLED"
    client.close()
