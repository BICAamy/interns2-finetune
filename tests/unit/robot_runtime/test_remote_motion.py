from __future__ import annotations

import secrets

import pytest

from robot_runtime.gateway_session import GatewaySessionManager
from robot_runtime.provider import RobotRuntimeServiceError
from robot_runtime.providers.huayan_real import HuayanRealStubProvider
from robot_runtime.remote_motion import RemoteMotionPolicy
from surgical_contracts import (
    CommandExecutionStatus,
    CoordinateFrame,
    ErrorCode,
    GatewayCommandKind,
    GatewayHandshake,
    GatewayHello,
    LinkState,
    MoveRelativeRequest,
    MotionControlRequest,
    MotionStopConfirmation,
    RobotActionRequest,
    RobotCommandResult,
    RobotCommandKind,
    RobotConnectionState,
    SoftwareStopResult,
    StopDelivery,
    ToolStatus,
    hello_auth_tag,
)
from tests.unit.robot_runtime.test_gateway_session import (
    DEVICE_SN,
    MODEL,
    SECRET,
    VERSION,
    state_frame,
)


def enabled_provider():
    clock = [1_000_000_000]
    sessions = GatewaySessionManager(
        secret=SECRET,
        gateway_id="mac-edge-test",
        device_sn=DEVICE_SN,
        robot_model=MODEL,
        package_versions=(VERSION,),
        stale_ms=250,
        gateway_timeout_ms=1000,
        transit_budget_ms=10,
        clock_ns=lambda: clock[0],
    )
    challenge = sessions.new_challenge()
    session_id = secrets.token_hex(16)
    handshake = GatewayHandshake(
        gateway_session_id=session_id,
        device_sn=DEVICE_SN,
        robot_model=MODEL,
        package_version=VERSION,
    )
    greeting = GatewayHello(
        gateway_id="mac-edge-test",
        challenge=challenge,
        handshake=handshake,
        auth_tag=hello_auth_tag(
            SECRET,
            gateway_id="mac-edge-test",
            challenge=challenge,
            handshake=handshake,
        ),
    )
    sessions.open(greeting, challenge=challenge, connection_key="socket")
    frame = state_frame(session_id)
    frame = frame.model_copy(update={
        "state": frame.state.model_copy(update={
            "connections": RobotConnectionState(
                gateway=LinkState.CONNECTED,
                datasheet=LinkState.CONNECTED,
                command_socket=LinkState.CONNECTED,
                controller_box=LinkState.CONNECTED,
            ),
            "enabled": True,
            "moving": False,
            "potentially_moving": False,
            "in_position": True,
            "physical_estop_active": False,
            "emergency_stop_circuit_fault": False,
            "safeguard_active": False,
            "safeguard_circuit_fault": False,
        })
    })
    sessions.ingest_state(frame, connection_key="socket")
    provider = HuayanRealStubProvider(
        sessions,
        remote_motion_policy=RemoteMotionPolicy(
            tcp_name="TCP",
            ucs_name="Base",
            max_speed_mm_s=5,
            max_step_mm=10,
            max_absolute_displacement_mm=10,
            max_rotation_deg=90,
            max_joint_speed_deg_s=30,
            max_joint_acceleration_deg_s2=60,
        ),
    )
    return sessions, provider, session_id


def test_proposal_is_inert_until_same_fingerprint_is_confirmed() -> None:
    _sessions, provider, session_id = enabled_provider()
    request = MoveRelativeRequest(
        command_id="remote-relative-1",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    record, created = provider.submit(
        RobotCommandKind.MOVE_RELATIVE,
        request,
    )
    assert created
    assert record.status == CommandExecutionStatus.QUEUED
    proposal = record.result["proposal"]
    assert proposal["executable"] is False
    assert proposal["web_confirmed"] is False
    assert provider.take_gateway_command(session_id) is None

    with pytest.raises(RobotRuntimeServiceError, match="fingerprint"):
        provider.confirm_command(request.command_id, "0" * 64)

    confirmed = provider.confirm_command(request.command_id, proposal["fingerprint"])
    assert confirmed.status == CommandExecutionStatus.RUNNING
    dispatched = provider.take_gateway_command(session_id)
    assert dispatched is not None
    assert dispatched.envelope.payload.translation_mm == (1.0, 0.0, 0.0)
    assert provider.take_gateway_command(session_id) is None
    assert provider.acknowledge_gateway_command(
        dispatched.envelope.command_id,
        dispatched.fingerprint,
        session_id,
    ) is True

    final_pose = dispatched.envelope.expected_start_pose_robot_base.model_copy(update={
        "translation_mm": (
            dispatched.envelope.expected_start_pose_robot_base.translation_mm[0] + 1,
            *dispatched.envelope.expected_start_pose_robot_base.translation_mm[1:],
        )
    })
    provider.ingest_gateway_result(
        dispatched.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=request.command_id,
            command_kind=GatewayCommandKind.MOVE_RELATIVE,
            status=ToolStatus.SUCCESS,
            controller_waypoint_id="Fremote",
            final_pose_robot_base=final_pose,
        ),
    )
    completed = provider.get_command(request.command_id)
    assert completed.status == CommandExecutionStatus.SUCCEEDED
    assert completed.result["completed"] is True
    assert completed.result["final_tcp_position"]["source"] == "structured_data"


def test_same_id_different_payload_and_disconnect_are_never_replayed() -> None:
    _sessions, provider, session_id = enabled_provider()
    first = MoveRelativeRequest(
        command_id="remote-relative-2",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    record, _ = provider.submit(
        RobotCommandKind.MOVE_RELATIVE,
        first,
    )
    with pytest.raises(RobotRuntimeServiceError, match="different arguments"):
        provider.submit(
            RobotCommandKind.MOVE_RELATIVE,
            first.model_copy(update={"translation_mm": (2, 0, 0)}),
        )
    fingerprint = record.result["proposal"]["fingerprint"]
    provider.confirm_command(first.command_id, fingerprint)
    assert provider.take_gateway_command(session_id) is not None
    provider.gateway_disconnected(session_id)
    failed = provider.get_command(first.command_id)
    assert failed.status == CommandExecutionStatus.FAILED
    assert "will not replay" in failed.error.message
    assert provider.take_gateway_command(session_id) is None


def test_gateway_failure_preserves_mac_error_code_and_reason() -> None:
    _sessions, provider, session_id = enabled_provider()
    request = MoveRelativeRequest(
        command_id="remote-relative-detailed-failure",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    record, _ = provider.submit(RobotCommandKind.MOVE_RELATIVE, request)
    fingerprint = record.result["proposal"]["fingerprint"]
    provider.confirm_command(request.command_id, fingerprint)
    dispatched = provider.take_gateway_command(session_id)
    assert dispatched is not None
    assert provider.acknowledge_gateway_command(
        dispatched.envelope.command_id,
        dispatched.fingerprint,
        session_id,
    ) is True

    provider.ingest_gateway_result(
        dispatched.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=request.command_id,
            command_kind=GatewayCommandKind.MOVE_RELATIVE,
            status=ToolStatus.FAILED,
            error_code=ErrorCode.OUT_OF_WORKSPACE,
            error_message="ValueError: path leaves approved workspace",
        ),
    )
    failed = provider.get_command(request.command_id)
    assert failed.status == CommandExecutionStatus.FAILED
    assert failed.error.code == ErrorCode.OUT_OF_WORKSPACE
    assert failed.error.message == "ValueError: path leaves approved workspace"


def test_software_stop_preempts_running_motion_and_returns_real_stopped_state() -> None:
    _sessions, provider, session_id = enabled_provider()
    motion = MoveRelativeRequest(
        command_id="remote-motion-before-stop",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    proposed, _ = provider.submit(RobotCommandKind.MOVE_RELATIVE, motion)
    fingerprint = proposed.result["proposal"]["fingerprint"]
    provider.confirm_command(motion.command_id, fingerprint)
    assert provider.take_gateway_command(session_id) is not None

    stop_request = RobotActionRequest(command_id="real-software-stop")
    stop_record, created = provider.submit(RobotCommandKind.STOP, stop_request)
    assert created is True
    assert stop_record.status == CommandExecutionStatus.RUNNING
    dispatched_stop = provider.take_gateway_command(session_id)
    assert dispatched_stop is not None
    assert (
        dispatched_stop.envelope.command_kind
        == GatewayCommandKind.SOFTWARE_STOP_REQUEST
    )
    assert provider.acknowledge_gateway_command(
        stop_request.command_id,
        dispatched_stop.fingerprint,
        session_id,
    ) is True
    provider.ingest_gateway_result(
        dispatched_stop.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=stop_request.command_id,
            command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
            status=ToolStatus.SUCCESS,
            software_stop=SoftwareStopResult(
                delivery=StopDelivery.SENT,
                motion_stop=MotionStopConfirmation.CONFIRMED,
            ),
        ),
    )
    completed = provider.get_command(stop_request.command_id)
    assert completed.status == CommandExecutionStatus.SUCCEEDED
    assert completed.result["operation"] == RobotCommandKind.STOP.value
    assert completed.result["state"]["mode"] == "real"
    assert completed.result["state"]["motion_state"] == "stopped"
    assert completed.result["state"]["estop"] is False


def test_software_stop_accepts_confirmed_preflight_cancellation_without_robot_write() -> None:
    _sessions, provider, session_id = enabled_provider()
    motion = MoveRelativeRequest(
        command_id="remote-motion-cancel-before-write",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    proposed, _ = provider.submit(RobotCommandKind.MOVE_RELATIVE, motion)
    provider.confirm_command(
        motion.command_id,
        proposed.result["proposal"]["fingerprint"],
    )
    dispatched_motion = provider.take_gateway_command(session_id)
    assert dispatched_motion is not None
    assert provider.acknowledge_gateway_command(
        motion.command_id,
        dispatched_motion.fingerprint,
        session_id,
    ) is True

    stop_request = RobotActionRequest(command_id="cancel-preflight-stop")
    provider.submit(RobotCommandKind.STOP, stop_request)
    stop_frame = provider.take_gateway_command(session_id)
    assert stop_frame is not None
    assert provider.acknowledge_gateway_command(
        stop_request.command_id,
        stop_frame.fingerprint,
        session_id,
    ) is True
    provider.ingest_gateway_result(
        stop_frame.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=stop_request.command_id,
            command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
            status=ToolStatus.SUCCESS,
            software_stop=SoftwareStopResult(
                delivery=StopDelivery.NOT_SENT,
                motion_stop=MotionStopConfirmation.CONFIRMED,
            ),
        ),
    )

    completed = provider.get_command(stop_request.command_id)
    assert completed.status == CommandExecutionStatus.SUCCEEDED
    assert completed.result["state"]["motion_state"] == "stopped"
    assert "before the first WayPoint" in completed.result["message"]


def test_pause_and_resume_update_the_same_real_motion_record() -> None:
    _sessions, provider, session_id = enabled_provider()
    motion = MoveRelativeRequest(
        command_id="remote-motion-pause-resume",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    proposed, _ = provider.submit(RobotCommandKind.MOVE_RELATIVE, motion)
    provider.confirm_command(
        motion.command_id,
        proposed.result["proposal"]["fingerprint"],
    )
    pause_request = MotionControlRequest(
        command_id="real-pause-control",
        target_command_id=motion.command_id,
        operation="pause",
    )
    pause_record, created = provider.submit(RobotCommandKind.PAUSE, pause_request)
    assert created is True
    assert pause_record.status == CommandExecutionStatus.RUNNING

    # Even if the operator clicks Stop immediately after web confirmation,
    # the just-confirmed motion must reach the Mac before its pause frame.
    dispatched_motion = provider.take_gateway_command(session_id)
    assert dispatched_motion is not None
    assert dispatched_motion.envelope.command_kind == GatewayCommandKind.MOVE_RELATIVE
    assert provider.acknowledge_gateway_command(
        motion.command_id,
        dispatched_motion.fingerprint,
        session_id,
    ) is True
    pause_frame = provider.take_gateway_command(session_id)
    assert pause_frame is not None
    assert pause_frame.envelope.command_kind == GatewayCommandKind.PAUSE_REQUEST
    assert provider.acknowledge_gateway_command(
        pause_request.command_id,
        pause_frame.fingerprint,
        session_id,
    ) is True
    provider.ingest_gateway_result(
        pause_frame.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=pause_request.command_id,
            command_kind=GatewayCommandKind.PAUSE_REQUEST,
            status=ToolStatus.SUCCESS,
        ),
    )
    assert provider.get_command(pause_request.command_id).status == (
        CommandExecutionStatus.SUCCEEDED
    )
    assert provider.get_command(motion.command_id).status == (
        CommandExecutionStatus.PAUSED
    )

    resume_request = MotionControlRequest(
        command_id="real-resume-control",
        target_command_id=motion.command_id,
        operation="resume",
    )
    resume_record, created = provider.submit(RobotCommandKind.RESUME, resume_request)
    assert created is True
    assert resume_record.status == CommandExecutionStatus.RUNNING
    resume_frame = provider.take_gateway_command(session_id)
    assert resume_frame is not None
    assert resume_frame.envelope.command_kind == GatewayCommandKind.RESUME_REQUEST
    assert provider.acknowledge_gateway_command(
        resume_request.command_id,
        resume_frame.fingerprint,
        session_id,
    ) is True
    provider.ingest_gateway_result(
        resume_frame.fingerprint,
        RobotCommandResult(
            gateway_session_id=session_id,
            command_id=resume_request.command_id,
            command_kind=GatewayCommandKind.RESUME_REQUEST,
            status=ToolStatus.SUCCESS,
        ),
    )
    assert provider.get_command(resume_request.command_id).status == (
        CommandExecutionStatus.SUCCEEDED
    )
    assert provider.get_command(motion.command_id).status == (
        CommandExecutionStatus.RUNNING
    )


def test_gateway_receipt_ttl_uses_server_monotonic_clock() -> None:
    _sessions, provider, session_id = enabled_provider()
    request = MoveRelativeRequest(
        command_id="remote-relative-expired-on-delivery",
        translation_mm=(1, 0, 0),
        frame=CoordinateFrame.ROBOT_BASE,
        speed_mm_s=2,
    )
    record, _ = provider.submit(RobotCommandKind.MOVE_RELATIVE, request)
    fingerprint = record.result["proposal"]["fingerprint"]
    provider.confirm_command(request.command_id, fingerprint)
    dispatched = provider.take_gateway_command(session_id)
    assert dispatched is not None

    assert provider.remote_motion is not None
    provider.remote_motion._delivery_deadlines_ns[request.command_id] = 0
    assert provider.acknowledge_gateway_command(
        request.command_id,
        dispatched.fingerprint,
        session_id,
    ) is False
    failed = provider.get_command(request.command_id)
    assert failed.status == CommandExecutionStatus.FAILED
    assert failed.error.code == ErrorCode.COMMAND_EXPIRED
    assert failed.error.message == (
        "proposal did not reach the Mac before its 30-second TTL"
    )
