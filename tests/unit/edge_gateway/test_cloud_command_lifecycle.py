from __future__ import annotations

import threading
import time
from collections import deque

from edge_gateway.cloud_transport import CloudTransport
from surgical_contracts import (
    CoordinateFrame,
    DistanceUnit,
    ErrorCode,
    GatewayCommandFrame,
    GatewayCommandKind,
    GatewayHeartbeat,
    LinkState,
    MotionSafetyLimits,
    MotionStopConfirmation,
    MoveRelativeRequest,
    Pose6D,
    RobotCommandEnvelope,
    RobotCommandResult,
    SoftwareStopRequest,
    SoftwareStopResult,
    StopDelivery,
    ToolStatus,
    command_fingerprint,
)


SESSION = "a" * 32


class _Connection:
    def __init__(self) -> None:
        self.closed = threading.Event()

    def close(self) -> None:
        self.closed.set()


class _ScriptedConnection:
    def __init__(self, responses: list[str]) -> None:
        self.responses = deque(responses)
        self.sent: list[str] = []

    def send(self, payload: str) -> None:
        self.sent.append(payload)

    def recv(self, *, timeout: float) -> str:
        del timeout
        return self.responses.popleft()


def _heartbeat() -> GatewayHeartbeat:
    return GatewayHeartbeat(
        gateway_session_id=SESSION,
        message_sequence=1,
        datasheet=LinkState.CONNECTED,
        command_socket=LinkState.CONNECTED,
    )


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


def _stop_frame() -> GatewayCommandFrame:
    now_ms = time.time_ns() // 1_000_000
    request = SoftwareStopRequest(command_id="priority-stop")
    envelope = RobotCommandEnvelope(
        gateway_session_id=SESSION,
        command_id=request.command_id,
        command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
        created_at_ms=now_ms,
        expires_at_ms=now_ms + 30_000,
        based_on_robot_state_sequence=2,
        payload=request,
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


def test_mac_does_not_compare_server_ttl_with_its_wall_clock() -> None:
    called = False

    def handler(envelope, _fingerprint):
        nonlocal called
        called = True
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=ErrorCode.ROBOT_TIMEOUT,
            error_message="handler ran after server authorization",
        )

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
        received_at_monotonic_ns=time.monotonic_ns(),
    )

    assert called is True
    assert transport._command_result is not None
    result = transport._command_result.result
    assert result.error_code == ErrorCode.ROBOT_TIMEOUT
    assert result.error_message == "handler ran after server authorization"


def test_server_denial_does_not_start_mac_command_handler() -> None:
    called = threading.Event()
    frame = _frame()
    connection = _ScriptedConnection([
        frame.model_dump_json(),
        (
            '{"type":"ack","message_sequence":1,'
            f'"command_id":"{frame.envelope.command_id}",'
            '"execute":false,"error_code":"COMMAND_EXPIRED"}'
        ),
    ])
    transport = CloudTransport(
        "ws://127.0.0.1:18001/v1/gateway/connect",
        secret=b"x" * 32,
        gateway_id="test-gateway",
        command_handler=lambda *_args: called.set(),
    )
    transport._connection = connection
    transport.session_id = SESSION

    transport._send_and_confirm(_heartbeat())

    assert not called.is_set()
    assert transport._active_command_id is None
    assert transport._command_thread is None


def test_mac_starts_handler_only_after_server_execution_authorization() -> None:
    called = threading.Event()
    frame = _frame()

    def handler(envelope, _fingerprint):
        called.set()
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=ErrorCode.ROBOT_TIMEOUT,
        )

    connection = _ScriptedConnection([
        frame.model_dump_json(),
        (
            '{"type":"ack","message_sequence":1,'
            f'"command_id":"{frame.envelope.command_id}",'
            '"execute":true,"error_code":null}'
        ),
    ])
    transport = CloudTransport(
        "ws://127.0.0.1:18001/v1/gateway/connect",
        secret=b"x" * 32,
        gateway_id="test-gateway",
        command_handler=handler,
    )
    transport._connection = connection
    transport.session_id = SESSION

    transport._send_and_confirm(_heartbeat())

    assert called.wait(timeout=1)
    assert transport._command_thread is not None
    transport._command_thread.join(timeout=1)
    assert transport._command_result is not None


def test_authenticated_stop_runs_while_motion_command_remains_active() -> None:
    called = threading.Event()
    frame = _stop_frame()

    def stop_handler(envelope, _fingerprint):
        called.set()
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.SUCCESS,
            software_stop=SoftwareStopResult(
                delivery=StopDelivery.SENT,
                motion_stop=MotionStopConfirmation.CONFIRMED,
            ),
        )

    connection = _ScriptedConnection([
        frame.model_dump_json(),
        (
            '{"type":"ack","message_sequence":1,'
            f'"command_id":"{frame.envelope.command_id}",'
            '"execute":true,"error_code":null}'
        ),
    ])
    transport = CloudTransport(
        "ws://127.0.0.1:18001/v1/gateway/connect",
        secret=b"x" * 32,
        gateway_id="test-gateway",
        command_handler=lambda *_args: None,
        stop_handler=stop_handler,
    )
    transport._connection = connection
    transport.session_id = SESSION
    transport._active_command_id = "motion-still-running"

    transport._send_and_confirm(_heartbeat())

    assert called.wait(timeout=1)
    assert transport._active_command_id == "motion-still-running"
    assert transport._stop_thread is not None
    transport._stop_thread.join(timeout=1)
    assert transport._stop_result is not None

