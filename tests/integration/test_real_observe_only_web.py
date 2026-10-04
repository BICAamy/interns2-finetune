from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from agent.tools.puncture_planner import FakePuncturePlannerClient
from agent.tools.robot import FakeRobotController
from robot_runtime.real_config import load_real_config
from simulation.runtime_config import load_simulation_motion_policy
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
    StubSimulationObserver,
    relative_command,
    settings,
    wait_for_status,
)
from web.backend.main import create_app
from web.backend.runtime import WebRuntime


def real_telemetry(sequence: int) -> RobotTelemetry:
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL,
        provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
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
        real_config_path="configs/robot-real.local.yaml",
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


def _dual_mode_client():
    real_settings = replace(
        settings(),
        runtime_mode=RuntimeMode.REAL,
        real_config_path="configs/robot-real.local.yaml",
    )
    real_observer = RealObserver()
    real_robot = FakeRobotController()
    runtime = WebRuntime(
        real_settings,
        parser=StubParser(relative_command()),
        robot=real_robot,
        planner=FakePuncturePlannerClient(),
        simulation_observer=real_observer,
    )
    simulation_robot = FakeRobotController()
    simulation_observer = StubSimulationObserver(simulation_robot)
    runtime._parsers[RuntimeMode.SIMULATION] = StubParser(relative_command())
    runtime._robots[RuntimeMode.SIMULATION] = simulation_robot
    runtime._observers[RuntimeMode.SIMULATION] = simulation_observer
    runtime._orchestrators[RuntimeMode.SIMULATION] = runtime.orchestrator.__class__(
        simulation_robot,
        runtime.planner,
        event_sink=runtime._on_tool_event,
    )
    runtime._default_robot_mode = RuntimeMode.SIMULATION
    return (
        TestClient(create_app(runtime, static_dir="/missing")),
        real_observer,
        simulation_robot,
    )


def test_real_and_simulation_motion_values_match_but_load_independently() -> None:
    real_config = load_real_config("configs/robot-real.local.yaml")
    simulation_policy = load_simulation_motion_policy("configs/simulation.yaml")

    assert simulation_policy.move_speed_mm_s == real_config.motion.speed_mm_s
    assert simulation_policy.max_speed_mm_s == real_config.limits.max_speed_mm_s
    assert (
        simulation_policy.max_relative_translation_mm
        == real_config.limits.max_step_mm
    )
    assert simulation_policy.entry_tolerance_mm == real_config.arrival.position_tolerance_mm

    simulation_data = yaml.safe_load(
        Path("configs/simulation.yaml").read_text(encoding="utf-8")
    )["entry_point_env"]
    assert tuple(simulation_data["workspace"]["low_mm"]) == real_config.limits.workspace_low_mm
    assert tuple(simulation_data["workspace"]["high_mm"]) == real_config.limits.workspace_high_mm
    assert tuple(
        tuple(pair) for pair in simulation_data["robot"]["joint_limits_deg"]
    ) == real_config.limits.joint_soft_limits_deg

    contaminated_settings = replace(
        settings(),
        runtime_mode=RuntimeMode.REAL,
        real_config_path="configs/robot-real.local.yaml",
        robot_simulation_fallback_base_url="http://127.0.0.1:8003",
        robot_move_speed_mm_s=11.0,
        max_robot_speed_mm_s=12.0,
        max_relative_translation_mm=13.0,
        entry_tolerance_mm=14.0,
    )
    runtime = WebRuntime(
        contaminated_settings,
        parser=StubParser(relative_command()),
        robot=FakeRobotController(),
        planner=FakePuncturePlannerClient(),
        simulation_observer=RealObserver(),
    )
    try:
        real_policy = runtime._orchestrators[RuntimeMode.REAL].policy
        fallback_policy = runtime._orchestrators[RuntimeMode.SIMULATION].policy
        assert real_policy.move_speed_mm_s == real_config.motion.speed_mm_s
        assert real_policy.max_speed_mm_s == real_config.limits.max_speed_mm_s
        assert fallback_policy.move_speed_mm_s == simulation_policy.move_speed_mm_s
        assert fallback_policy.max_speed_mm_s == simulation_policy.max_speed_mm_s
        assert (
            fallback_policy.max_relative_translation_mm
            == simulation_policy.max_relative_translation_mm
        )
        assert fallback_policy.entry_tolerance_mm == simulation_policy.entry_tolerance_mm
    finally:
        runtime.close()


def test_real_generic_routes_expose_only_actual_state() -> None:
    client, observer, robot = _client()
    with client:
        session = client.post("/api/sessions").json()
        base = f"/api/sessions/{session['session_id']}"
        generic = client.get(f"{base}/robot/telemetry")
        assert generic.status_code == 200
        payload = generic.json()
        assert payload["runtime_mode"] == "real"
        assert "control_mode" not in payload
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


def test_web_defaults_to_simulation_switches_to_live_real_and_falls_back() -> None:
    client, real_observer, _simulation_robot = _dual_mode_client()
    with client:
        health = client.get("/health").json()
        assert health["default_robot_mode"] == "simulation"
        assert health["available_robot_modes"] == ["real", "simulation"]

        session = client.post("/api/sessions").json()
        session_id = session["session_id"]
        assert session["robot_mode"] == "simulation"
        assert session["current_tcp"]["z"] == 100.0

        parsed = client.post(
            f"/api/sessions/{session_id}/commands/text",
            json={"prompt": "仿真机械臂沿 Z 正方向移动 8 毫米"},
        ).json()
        assert parsed["status"] == "awaiting_confirmation"
        assert parsed["motion_proposal"] is None
        confirmed = client.post(f"/api/sessions/{session_id}/confirm", json={})
        assert confirmed.status_code == 202
        completed = wait_for_status(client, session_id, {"completed", "failed"})
        assert completed["status"] == "completed"

        selected = client.put(
            f"/api/sessions/{session_id}/robot/mode",
            json={"mode": "real"},
        )
        assert selected.status_code == 200
        assert selected.json()["robot_mode"] == "real"
        assert selected.json()["current_tcp"] == {
            "x": 542.0,
            "y": 0.0,
            "z": 500.0,
            "unit": "mm",
            "frame": "robot_base",
            "source": None,
        }

        real_observer.state = real_observer.state.model_copy(
            update={"freshness": SourceFreshness.DISCONNECTED}
        )
        telemetry = client.get(
            f"/api/sessions/{session_id}/robot/telemetry"
        ).json()
        assert telemetry["runtime_mode"] == "simulation"
        fallback = client.get(f"/api/sessions/{session_id}").json()
        assert fallback["robot_mode"] == "simulation"
        assert "未连接机械臂，已自动退回仿真模式" in fallback["mode_notice"]


def test_selecting_unavailable_real_mode_stays_in_simulation_with_notice() -> None:
    client, real_observer, _simulation_robot = _dual_mode_client()
    real_observer.state = real_observer.state.model_copy(
        update={
            "connections": RobotConnectionState(
                gateway=LinkState.DISCONNECTED,
                datasheet=LinkState.DISCONNECTED,
                command_socket=LinkState.DISCONNECTED,
                controller_box=LinkState.DISCONNECTED,
            ),
            "freshness": SourceFreshness.DISCONNECTED,
        }
    )
    with client:
        session_id = client.post("/api/sessions").json()["session_id"]
        response = client.put(
            f"/api/sessions/{session_id}/robot/mode",
            json={"mode": "real"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["robot_mode"] == "simulation"
        assert "未连接机械臂" in payload["mode_notice"]
