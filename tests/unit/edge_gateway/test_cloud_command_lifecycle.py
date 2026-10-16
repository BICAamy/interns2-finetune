from __future__ import annotations

import threading
import time

from edge_gateway.cloud_transport import CloudTransport
from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    ErrorCode,
    GatewayCommandFrame,
    GatewayCommandKind,
    MotionSafetyLimits,
    MoveRelativeRequest,
    Pose6D,
    RobotCommandEnvelope,
    RobotCommandResult,
    ToolStatus,
    command_fingerprint,
)


SESSION = "a" * 32


class _Connection:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


def _frame(*, now_ms: int | None = None) -> GatewayCommandFrame:
    now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    pose = Pose6D(
        translation_mm=(500, 0, 300),
        rotation_rpy_deg=(0, 0, 0),
        quaternion_xyzw=(0, 0, 0, 1),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )
    request = MoveRelativeRequest(
        command_id="thread-lifecycle",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    envelope = RobotCommandEnvelope(
        gateway_session_id=SESSION,
        command_id=request.command_id,
        command_kind=GatewayCommandKind.MOVE_RELATIVE,
        created_at_ms=now_ms - 100,
        expires_at_ms=now_ms + 30_000,
        based_on_robot_state_sequence=1,
        expected_start_pose_robot_base=pose,
        expected_tcp_name="TCP",
        expected_ucs_name="Base",
        payload=request,
        safety_limits=MotionSafetyLimits(
            max_speed_mm_s=5,
            max_step_mm=10,
            max_rotation_deg=90,
            max_joint_speed_deg_s=30,
            max_joint_acceleration_deg_s2=60,
        ),
        operator_confirmation_id="web-confirmed",
    )
    return GatewayCommandFrame(
        fingerprint=command_fingerprint(envelope),
        envelope=envelope,
    )


def test_disconnect_waits_for_old_command_thread_before_clearing_owner() -> None:
    entered = threading.Event()
    release = threading.Event()

    def handler(envelope, _fingerprint):
        entered.set()
        assert release.wait(timeout=2)
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=ErrorCode.ROBOT_TIMEOUT,
            error_message="deliberate test failure",
        )

    transport = CloudTransport(
        "ws://127.0.0.1:18001/v1/gateway/connect",
        secret=b"x" * 32,
        gateway_id="test-gateway",
        command_handler=handler,
    )
    frame = _frame()
    connection = _Connection()
    transport._connection = connection
    transport.session_id = SESSION
    worker = threading.Thread(
        target=transport._run_command,
        args=(frame,),
        kwargs={
            "session_id": SESSION,
            "received_at_ms": time.time_ns() // 1_000_000,
            "received_at_monotonic_ns": time.monotonic_ns(),
        },
    )
    with transport._command_lock:
        transport._active_command_id = frame.envelope.command_id
        transport._command_thread = worker
    worker.start()
    assert entered.wait(timeout=1)

    closed = threading.Event()
    closer = threading.Thread(
        target=lambda: (transport.close(), closed.set()),
    )
    closer.start()
    assert connection.closed.wait(timeout=1)
    assert not closed.wait(timeout=0.05)
    assert transport._active_command_id == frame.envelope.command_id

    release.set()
    assert closed.wait(timeout=1)
    closer.join(timeout=1)
    assert transport._active_command_id is None
    assert transport._command_thread is None


def test_proposal_ttl_is_checked_only_at_mac_receipt() -> None:
    called = False

    def handler(_envelope, _fingerprint):
        nonlocal called
        called = True
        raise AssertionError("expired proposal must not reach command handler")

    now_ms = time.time_ns() // 1_000_000
    frame = _frame(now_ms=now_ms - 31_000)
    transport = CloudTransport(
        "ws://127.0.0.1:18001/v1/gateway/connect",
        secret=b"x" * 32,
        gateway_id="test-gateway",
        command_handler=handler,
    )
    transport.session_id = SESSION
    transport._active_command_id = frame.envelope.command_id
    transport._run_command(
        frame,
        session_id=SESSION,
        received_at_ms=now_ms,
        received_at_monotonic_ns=time.monotonic_ns(),
    )

    assert called is False
    assert transport._command_result is not None
    result = transport._command_result.result
    assert result.error_code == ErrorCode.COMMAND_EXPIRED
    assert "reach the Mac" in (result.error_message or "")

