from __future__ import annotations

import threading
import time

from edge_gateway.direct_jog import DirectJogExecutor
from surgical_contracts import (
    CoordinateFrame,
    DirectJogRequest,
    DistanceUnit,
    GatewayCommandKind,
    LinkState,
    MotionSafetyLimits,
    MotionStopConfirmation,
    Pose6D,
    RobotCommandEnvelope,
    RobotConnectionState,
    RobotProvider,
    RobotTelemetry,
    RuntimeMode,
    SourceFreshness,
    StopDelivery,
    ToolStatus,
    command_fingerprint,
)


class JogClient:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.keepalives = 0
        self.stopped = 0

    def start_long_jog(self, *, kind: str, axis: int, direction: int) -> bool:
        assert (kind, axis, direction) == ("cartesian", 3, -1)
        self.started.set()
        return True

    def keep_long_jog_alive(self) -> bool:
        self.keepalives += 1
        return True

    def stop_long_jog(self) -> bool:
        self.stopped += 1
        return True


def telemetry() -> RobotTelemetry:
    return RobotTelemetry(
        runtime_mode=RuntimeMode.REAL,
        provider=RobotProvider.HUAYAN_EDGE_GATEWAY,
        sequence=1,
        freshness=SourceFreshness.FRESH,
        connections=RobotConnectionState(
            gateway=LinkState.CONNECTED,
            datasheet=LinkState.CONNECTED,
            command_socket=LinkState.CONNECTED,
            controller_box=LinkState.CONNECTED,
        ),
        state_age_ms=1,
        gateway_session_id="session-1",
        joint_positions_deg=(0, 0, 0, 0, 0, 0),
        actual_pose_robot_base=Pose6D(
            translation_mm=(400, 0, 500),
            rotation_rpy_deg=(0, 0, 0),
            quaternion_xyzw=(0, 0, 0, 1),
            frame=CoordinateFrame.ROBOT_BASE,
            unit=DistanceUnit.MILLIMETER,
        ),
        potentially_moving=False,
        moving=False,
        in_position=True,
        enabled=True,
        physical_estop_active=False,
        emergency_stop_circuit_fault=False,
        safeguard_active=False,
        safeguard_circuit_fault=False,
        controller_is_simulation=False,
    )


def jog_envelope() -> RobotCommandEnvelope:
    request = DirectJogRequest(
        command_id="held-jog-1",
        kind="cartesian",
        axis=3,
        direction=-1,
        speed_scale=0.75,
    )
    return RobotCommandEnvelope(
        gateway_session_id="session-1",
        command_id=request.command_id,
        command_kind=GatewayCommandKind.DIRECT_JOG,
        created_at_ms=1,
        expires_at_ms=1000,
        based_on_robot_state_sequence=1,
        expected_start_pose_robot_base=telemetry().actual_pose_robot_base,
        expected_tcp_name="TCP",
        expected_ucs_name="Base",
        payload=request,
        safety_limits=MotionSafetyLimits(
            max_speed_mm_s=100,
            max_step_mm=100,
            max_rotation_deg=90,
            max_joint_speed_deg_s=100,
            max_joint_acceleration_deg_s2=100,
        ),
        operator_confirmation_id="web-held-jog-1",
    )


def test_long_jog_is_kept_alive_and_closes_once_on_authenticated_stop() -> None:
    client = JogClient()
    executor = DirectJogExecutor(
        client=client,  # type: ignore[arg-type]
        snapshot=telemetry,
        cloud_connected=lambda: True,
        keepalive_interval_s=0.01,
        motion_timeout_s=1,
        stop_confirmation_s=0.1,
    )
    envelope = jog_envelope()
    result_holder = {}
    worker = threading.Thread(
        target=lambda: result_holder.setdefault(
            "result", executor.execute(envelope, command_fingerprint(envelope)),
        )
    )
    worker.start()
    assert client.started.wait(0.2)
    time.sleep(0.035)
    stop = executor.request_authenticated_stop("stop-1", timeout_s=0.5)
    worker.join(0.5)

    assert not worker.is_alive()
    assert client.keepalives >= 2
    assert client.stopped == 1
    assert stop.delivery == StopDelivery.SENT
    assert stop.motion_stop == MotionStopConfirmation.CONFIRMED
    assert result_holder["result"].status == ToolStatus.SUCCESS
