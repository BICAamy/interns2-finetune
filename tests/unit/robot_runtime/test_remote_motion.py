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
    GatewayCommandKind,
    GatewayHandshake,
    GatewayHello,
    LinkState,
    MoveRelativeRequest,
    RobotCommandResult,
    RobotCommandKind,
    RobotConnectionState,
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
