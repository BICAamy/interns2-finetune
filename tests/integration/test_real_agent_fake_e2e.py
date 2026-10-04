"""Step 12: server -> Mac -> fake -> actual feedback -> web session."""

from __future__ import annotations

from dataclasses import replace
import os
import json
from pathlib import Path
import socket
import threading
import time

from fastapi.testclient import TestClient
import uvicorn

from agent.tools.puncture_planner import FakePuncturePlannerClient
from agent.tools.robot import RobotRuntimeHTTPController
from edge_gateway.command_journal import CommandJournal
from edge_gateway.commissioning_runtime import make_approval
from edge_gateway.config import EdgeConfig
from edge_gateway.fake_motion import LocalMotionTiming, LocalMotionTrial
from edge_gateway.huayan.fake_motion_client import FakeMotionClient
from edge_gateway.main import EdgeGateway
from edge_gateway.preflight import ControllerReadback
from edge_gateway.remote_motion import RemoteMotionExecutor
from robot_runtime.api import create_app as create_robot_app
from robot_runtime.gateway_session import GatewaySessionManager
from robot_runtime.providers.huayan_real import HuayanRealStubProvider
from robot_runtime.real_config import load_real_config
from robot_runtime.remote_motion import RemoteMotionPolicy
from surgical_contracts import (
    CommandIntent, CoordinateFrame, CoordinateSource, DistanceUnit, ErrorCode,
    GatewayCommandKind, ParsedCommand, Point3D, RelativeMotion,
    RobotCommandResult, SetEnabledRequest, ToolStatus, command_fingerprint,
)
from tests.fakes.huayan_controller import FakeHuayanController
from tests.integration.test_agent_web import StubParser, relative_command, settings
from web.backend.main import create_app as create_web_app
from web.backend.runtime import WebRuntime


SECRET = b"step12-fake-e2e-shared-secret-32-bytes"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class _ActualFeedbackObserver:
    def __init__(self, robot: RobotRuntimeHTTPController) -> None:
        self.robot = robot

    def get_telemetry(self):
        return self.robot.get_telemetry()

    def get_mirror_status(self):
        return {
            "frame_sequence": 1,
            "source_sequence": self.robot.get_telemetry().sequence,
            "calibrated": True,
            "warning": "FAKE E2E / ACTUAL FEEDBACK",
            "reason": "step12_fake",
        }

    def close(self) -> None:
        pass


def test_web_confirmation_runs_combined_and_absolute_fake_motion(tmp_path: Path) -> None:
    secret_file = tmp_path / "gateway-auth.local"
    secret_file.write_bytes(SECRET)
    os.chmod(secret_file, 0o600)
    config = load_real_config("configs/robot-real.local.yaml")
    config = config.model_copy(update={
        "controller": config.controller.model_copy(update={
            "device_sn": "FAKE-E05-001",
            "model": "E05-Pro",
            "package_versions": ["6.3.6.20240305"],
        }),
        "motion": config.motion.model_copy(update={"speed_mm_s": 2.0}),
        "deadlines": config.deadlines.model_copy(update={
            "startup_ms": 1000,
            "motion_ms": 3000,
            "stop_ack_ms": 1000,
        }),
        "arrival": config.arrival.model_copy(update={
            "stable_samples": 2,
            "dwell_ms": 50,
        }),
    })
    approval = make_approval(config, package_version="6.3.6.20240305")
    sessions = GatewaySessionManager(
        secret=SECRET,
        gateway_id="mac-edge-step12",
        device_sn="FAKE-E05-001",
        robot_model="E05-Pro",
        package_versions=("6.3.6.20240305",),
        stale_ms=config.deadlines.state_stale_ms,
    )
    provider = HuayanRealStubProvider(
        sessions,
        remote_motion_policy=RemoteMotionPolicy(
            tcp_name=config.tool.tcp_name,
            ucs_name="Base",
            max_speed_mm_s=config.limits.max_speed_mm_s,
            max_step_mm=config.limits.max_step_mm,
            max_absolute_displacement_mm=config.limits.max_absolute_displacement_mm,
        ),
    )
    robot_port = _free_port()
    robot_server = uvicorn.Server(uvicorn.Config(
        create_robot_app(provider=provider, mode="real"),
        host="127.0.0.1",
        port=robot_port,
        log_level="error",
        ws_max_size=64 * 1024,
    ))
    robot_thread = threading.Thread(target=robot_server.run, daemon=True)
    robot_thread.start()
    gateway_errors: list[Exception] = []
    gateway: EdgeGateway | None = None
    gateway_thread: threading.Thread | None = None
    motion_client: FakeMotionClient | None = None
    journal: CommandJournal | None = None
    try:
        deadline = time.monotonic() + 3
        robot_http = RobotRuntimeHTTPController(
            f"http://127.0.0.1:{robot_port}",
            http_timeout_s=2,
            command_timeout_s=5,
            poll_interval_s=0.02,
        )
        while time.monotonic() < deadline:
            try:
                robot_http.get_runtime_health()
                break
            except Exception:
                time.sleep(0.02)
        else:
            raise AssertionError("robot runtime did not start")

        with FakeHuayanController(
            accept_fake_motion=True,
            initial_enabled=False,
            simulate_waypoint_motion=True,
            waypoint_motion_s=0.2,
        ) as fake:
            motion_client = FakeMotionClient(
                "127.0.0.1", fake.command_port, timeout_s=0.5,
            )
            motion_client.connect()
            journal = CommandJournal(tmp_path / "step12-remote.journal")
            holder: dict[str, EdgeGateway] = {}

            def snapshot():
                return holder["gateway"].local_telemetry()

            def readback() -> ControllerReadback:
                return ControllerReadback(
                    tcp_name=config.tool.tcp_name,
                    ucs_name="Base",
                    tcp_xyzrpy=(0.0,) * 6,
                    ucs_xyzrpy=(0.0,) * 6,
                    payload_kg=0.0,
                    center_of_gravity_mm=(0.0,) * 3,
                    base_installing_angle_deg=config.tool.mount_angle_deg,
                    group_error_code=0,
                    axis_error_codes=(0, 0, 0, 0, 0, 0),
                    active_program=False,
                    waypoint_id=motion_client.current_waypoint_id(),
                    controller_override=motion_client.current_override(),
                )

            timing = LocalMotionTiming(
                response_ms=config.deadlines.response_ms,
                start_ms=config.deadlines.startup_ms,
                motion_ms=config.deadlines.motion_ms,
                stop_confirmation_ms=config.deadlines.stop_ack_ms,
                stable_samples=config.arrival.stable_samples,
                dwell_ms=config.arrival.dwell_ms,
                position_tolerance_mm=config.arrival.position_tolerance_mm,
                orientation_tolerance_deg=config.arrival.orientation_tolerance_deg,
            )

            def trial_factory() -> LocalMotionTrial:
                return LocalMotionTrial(
                    client=motion_client,
                    journal=journal,
                    timing=timing,
                    approval=approval,
                    path_ik=lambda _point: snapshot().joint_positions_deg,
                )

            executor = RemoteMotionExecutor(
                trial_factory=trial_factory,
                snapshot=snapshot,
                readback=readback,
                feedback=lambda: (snapshot(), "step12 fake actual feedback"),
                poll_interval_s=0.02,
            )

            def command_handler(envelope, fingerprint):
                if envelope.command_kind in {
                    GatewayCommandKind.MOVE_RELATIVE,
                    GatewayCommandKind.MOVE_TO_ENTRY,
                }:
                    return executor.execute(envelope, fingerprint)
                if (
                    envelope.command_kind != GatewayCommandKind.SET_ENABLED
                    or command_fingerprint(envelope) != fingerprint
                    or not isinstance(envelope.payload, SetEnabledRequest)
                ):
                    return RobotCommandResult(
                        gateway_session_id=envelope.gateway_session_id,
                        command_id=envelope.command_id,
                        command_kind=envelope.command_kind,
                        status=ToolStatus.FAILED,
                        error_code=ErrorCode.INVALID_COMMAND_SCHEMA,
                    )
                desired = envelope.payload.enabled
                before_sequence = snapshot().sequence
                assert motion_client.set_enabled(desired)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    record, _events = holder["gateway"].state.snapshot()
                    if (
                        record is not None
                        and record.sequence > before_sequence
                        and record.sample.enabled is desired
                    ):
                        return RobotCommandResult(
                            gateway_session_id=envelope.gateway_session_id,
                            command_id=envelope.command_id,
                            command_kind=envelope.command_kind,
                            status=ToolStatus.SUCCESS,
                            confirmed_enabled=desired,
                        )
                    time.sleep(0.02)
                return RobotCommandResult(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=envelope.command_id,
                    command_kind=envelope.command_kind,
                    status=ToolStatus.FAILED,
                    error_code=ErrorCode.ROBOT_TIMEOUT,
                )
            edge_config = EdgeConfig(
                fake_command_port=fake.command_port,
                fake_datasheet_port=fake.datasheet_port,
                server_url=f"ws://127.0.0.1:{robot_port}/v1/gateway/connect",
                secret_file=secret_file,
                gateway_id="mac-edge-step12",
                datasheet_byte_order="little",
                audit_path=tmp_path / "edge.log",
                stale_ms=config.deadlines.state_stale_ms,
            )
            gateway = EdgeGateway(edge_config, command_handler=command_handler)
            holder["gateway"] = gateway

            def run_gateway() -> None:
                try:
                    gateway.run(max_runtime_s=8)
                except Exception as error:
                    gateway_errors.append(error)

            gateway_thread = threading.Thread(target=run_gateway, daemon=True)
            gateway_thread.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    if robot_http.get_runtime_health().status == "healthy":
                        break
                except Exception:
                    pass
                time.sleep(0.02)
            else:
                raise AssertionError("fake gateway did not become healthy")

            actual_before = robot_http.get_telemetry().actual_pose_robot_base.translation_mm
            web_settings = replace(
                settings(),
                runtime_mode="real",
                real_config_path="configs/robot-real.local.yaml",
                robot_simulation_base_url=f"http://127.0.0.1:{robot_port}",
                robot_move_speed_mm_s=2.0,
                max_robot_speed_mm_s=5.0,
                max_relative_translation_mm=20.0,
                robot_simulation_command_timeout=5.0,
                robot_simulation_poll_interval=0.02,
            )
            runtime = WebRuntime(
                web_settings,
                parser=StubParser(relative_command("step12-web-relative")),
                robot=robot_http,
                planner=FakePuncturePlannerClient(),
                simulation_observer=_ActualFeedbackObserver(robot_http),
            )
            with TestClient(create_web_app(runtime, static_dir="/missing")) as web:
                session_id = web.post("/api/sessions").json()["session_id"]
                enabled = web.post(
                    f"/api/sessions/{session_id}/robot/enabled",
                    json={"enabled": True},
                )
                assert enabled.status_code == 200, enabled.text
                assert enabled.json()["confirmed_enabled"] is True
                assert len([x for x in fake.received_commands if x.startswith(b"GrpEnable,")]) == 1
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    if robot_http.get_telemetry().enabled is True:
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("enabled feedback did not reach robot-runtime")
                def execute(command: ParsedCommand, prompt: str, *, reject_bad_fingerprint: bool = False):
                    runtime.parser = StubParser(command)
                    proposal_response = web.post(
                        f"/api/sessions/{session_id}/commands/text",
                        json={"prompt": prompt},
                    )
                    assert proposal_response.status_code == 200
                    proposed = proposal_response.json()
                    assert proposed["status"] == "awaiting_confirmation"
                    proposal = proposed["motion_proposal"]
                    assert proposal["executable"] is False
                    assert proposal["web_confirmed"] is False
                    assert len(proposal["fingerprint"]) == 64
                    before_count = len([
                        frame for frame in fake.received_commands
                        if frame.startswith(b"WayPoint,")
                    ])
                    if reject_bad_fingerprint:
                        mismatch = web.post(
                            f"/api/sessions/{session_id}/confirm",
                            json={"fingerprint": "0" * 64},
                        )
                        assert mismatch.status_code == 409
                        assert len([
                            frame for frame in fake.received_commands
                            if frame.startswith(b"WayPoint,")
                        ]) == before_count
                    confirmed = web.post(
                        f"/api/sessions/{session_id}/confirm",
                        json={"fingerprint": proposal["fingerprint"]},
                    )
                    assert confirmed.status_code == 202
                    duplicate = web.post(
                        f"/api/sessions/{session_id}/confirm",
                        json={"fingerprint": proposal["fingerprint"]},
                    )
                    assert duplicate.status_code == 409
                    deadline = time.monotonic() + 6
                    final = None
                    while time.monotonic() < deadline:
                        final = web.get(f"/api/sessions/{session_id}").json()
                        if final["status"] in {"completed", "failed"}:
                            break
                        time.sleep(0.03)
                    assert final is not None and final["status"] == "completed", json.dumps(final, ensure_ascii=False)
                    assert len([
                        frame for frame in fake.received_commands
                        if frame.startswith(b"WayPoint,")
                    ]) == before_count + 1
                    return final

                # Deliberately exceeds the old code-only 20 mm cap. Real mode
                # must use the checked-in YAML max_step_mm instead.
                combined_delta = (30.0, -3.0, 5.0)
                combined = ParsedCommand(
                    command_id="step12-web-combined",
                    intent=CommandIntent.MOVE_RELATIVE,
                    relative_motion=RelativeMotion(
                        delta_mm=combined_delta,
                        frame=CoordinateFrame.ROBOT_BASE,
                    ),
                    summary="Base 组合相对位移",
                )
                combined_final = execute(
                    combined,
                    "Base 坐标系 X+30、Y-3、Z+5 毫米",
                    reject_bad_fingerprint=True,
                )
                after_combined = robot_http.get_telemetry().actual_pose_robot_base
                assert all(
                    abs(actual - start - delta) < 0.01
                    for actual, start, delta in zip(
                        after_combined.translation_mm, actual_before, combined_delta,
                    )
                )
                assert abs(combined_final["current_tcp"]["z"] - after_combined.translation_mm[2]) < 0.01

                absolute_xyz = tuple(
                    value + delta
                    for value, delta in zip(after_combined.translation_mm, (-2.0, 4.0, 1.0))
                )
                absolute = ParsedCommand(
                    command_id="step12-web-absolute",
                    intent=CommandIntent.MOVE_TO_ENTRY,
                    entry_point=Point3D(
                        x=absolute_xyz[0], y=absolute_xyz[1], z=absolute_xyz[2],
                        frame=CoordinateFrame.ROBOT_BASE,
                        unit=DistanceUnit.MILLIMETER,
                        source=CoordinateSource.USER_TEXT,
                    ),
                    summary="移动到 Base 绝对 XYZ，保持当前实际姿态",
                )
                execute(
                    absolute,
                    "移动到 Base 绝对 XYZ，保持当前实际姿态",
                )
                after_absolute = robot_http.get_telemetry().actual_pose_robot_base
                assert all(
                    abs(actual - target) < 0.01
                    for actual, target in zip(after_absolute.translation_mm, absolute_xyz)
                )
                assert all(
                    abs(actual - expected) < 1e-6
                    for actual, expected in zip(
                        after_absolute.quaternion_xyzw,
                        after_combined.quaternion_xyzw,
                    )
                )
                assert journal.unresolved() == ()
            assert not gateway_errors
    finally:
        if gateway is not None:
            gateway.close()
        if gateway_thread is not None:
            gateway_thread.join(timeout=2)
        if motion_client is not None:
            motion_client.close()
        if journal is not None:
            journal.close()
        robot_server.should_exit = True
        robot_thread.join(timeout=3)
