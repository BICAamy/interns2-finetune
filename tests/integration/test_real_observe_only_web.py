from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from agent.tools.puncture_planner import FakePuncturePlannerClient
from agent.tools.robot import FakeRobotController
from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    LinkState,
    Pose6D,
    RobotConnectionState,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SimulationCameraControlRequest,
    SimulationCameraState,
    SourceFreshness,
)
from tests.integration.test_agent_web import (
    StubMJPEGStream,
    StubParser,
    relative_command,
    settings,
)
from web.backend.main import create_app
from web.backend.runtime import WebRuntime


def real_telemetry(sequence: int) -> RobotTelemetry:
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL,
        provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
        control_mode="observe-only",
        sequence=sequence,
        freshness=SourceFreshness.FRESH,
        gateway_session_id="session-step8-web",
        joint_positions_deg=(0.0, -13.573, 97.585, 0.918, 57.696, -39.035),
        state_age_ms=10.0,
        controller_is_simulation=False,
        actual_pose_robot_base=Pose6D(
            translation_mm=(500.0 + sequence, 0.0, 500.0),
            rotation_rpy_deg=(0.0, 0.0, 0.0),
            quaternion_xyzw=(0.0, 0.0, 0.0, 1.0),
            frame=CoordinateFrame.ROBOT_BASE,
            unit=DistanceUnit.MILLIMETER,
        ),
    )


class RealObserver:
    def __init__(self) -> None:
        self.state = real_telemetry(42).model_copy(
            update={
                "connections": RobotConnectionState(
                    gateway=LinkState.CONNECTED,
                    datasheet=LinkState.CONNECTED,
                    command_socket=LinkState.CONNECTED,
                    controller_box=LinkState.CONNECTED,
                ),
                "electrified": True,
                "enabled": False,
                "moving": False,
                "in_position": True,
                "fsm_code": 24,
                "physical_estop_active": False,
                "emergency_stop_circuit_fault": False,
                "safeguard_active": False,
                "safeguard_circuit_fault": False,
            }
        )
        self.camera_state = SimulationCameraState(
            preset="front",
            yaw_deg=0,
            pitch_deg=0,
            distance_m=1.65,
            target_m=(0.35, 0, 0.42),
            position_m=(0.35, -1.65, 0.42),
            updated_at_ms=1,
        )
        self.camera_calls = 0
        self.closed = False

    def get_telemetry(self):
        return self.state.model_copy(deep=True)

    def get_mirror_status(self):
        return {
            "frame_sequence": 19,
            "source_sequence": self.state.sequence,
            "calibrated": True,
            "warning": "COORDINATE CALIBRATED / TOOL TCP UNAVAILABLE / NOT FOR CONTROL",
            "reason": "coordinate_calibrated_tool_tcp_unavailable",
        }

    def get_camera_state(self):
        return self.camera_state.model_copy(deep=True)

    def control_camera(self, request: SimulationCameraControlRequest):
        self.camera_calls += 1
        self.camera_state = self.camera_state.model_copy(
            update={"preset": request.preset or "custom", "updated_at_ms": 2}
        )
        return self.get_camera_state()

    async def open_mjpeg(self):
        return StubMJPEGStream()

    def close(self) -> None:
        self.closed = True


def _client():
    real_settings = replace(
        settings(),
        runtime_mode=RuntimeMode.REAL,
        robot_control_mode="observe-only",
        real_config_path="configs/robot-real.local.yaml",
        real_config_sha256="a" * 64,
    )
    observer = RealObserver()
    robot = FakeRobotController()
    runtime = WebRuntime(
        real_settings,
        parser=StubParser(relative_command()),
        robot=robot,
        planner=FakePuncturePlannerClient(),
        simulation_observer=observer,
    )
    return TestClient(create_app(runtime, static_dir="/missing")), observer, robot


def test_real_generic_routes_expose_only_actual_observe_only_state() -> None:
    client, observer, robot = _client()
    with client:
        session = client.post("/api/sessions").json()
        base = f"/api/sessions/{session['session_id']}"
        generic = client.get(f"{base}/robot/telemetry")
        assert generic.status_code == 200
        payload = generic.json()
        assert payload["runtime_mode"] == "real"
        assert payload["control_mode"] == "observe-only"
        assert payload["sequence"] == 42
        assert payload["joint_positions_deg"][2] == 97.585
        assert payload["connections"] == {
            "server": "connected",
            "gateway": "connected",
            "datasheet": "connected",
            "command_socket": "connected",
            "controller_box": "connected",
        }
        assert payload["actual_tcp_robot_base"]["translation_mm"] == [542.0, 0.0, 500.0]
        assert payload["mirror_calibrated"] is True
        assert payload["tool_tcp_calibrated"] is False

        alias = client.get(f"{base}/simulation/telemetry")
        assert alias.status_code == 200
        assert alias.json()["runtime_mode"] == "real"
        assert client.get(f"{base}/robot/camera").status_code == 200
        assert client.put(
            f"{base}/robot/camera",
            json={"action": "preset", "preset": "left"},
        ).status_code == 200
        assert observer.camera_calls == 1
        stream = client.get(f"{base}/robot/stream.mjpeg")
        assert stream.status_code == 200
        assert b"step12" in stream.content
        assert robot.move_relative_calls == []
    assert observer.closed is False  # injected observer remains caller-owned


def test_real_stale_state_is_disconnected_for_ui_and_keeps_last_pose() -> None:
    client, observer, _robot = _client()
    observer.state = observer.state.model_copy(
        update={"freshness": SourceFreshness.STALE, "state_age_ms": 500.0}
    )
    with client:
        session_id = client.post("/api/sessions").json()["session_id"]
        payload = client.get(
            f"/api/sessions/{session_id}/robot/telemetry"
        ).json()
        assert payload["connected"] is False
        assert payload["freshness"] == "stale"
        assert payload["joint_positions_deg"][0] == 0.0
        assert payload["error"]["code"] == "ROBOT_STALE"
