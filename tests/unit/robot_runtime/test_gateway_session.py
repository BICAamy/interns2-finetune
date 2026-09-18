from __future__ import annotations

import secrets

import pytest

from edge_gateway.cloud_transport import telemetry_from_sample
from edge_gateway.huayan.datasheet_codec import DatasheetFrameDecoder
from edge_gateway.state_machine import SampleRecord
from edge_gateway.watchdog import StateWatchdog
from robot_runtime.gateway_session import GatewaySessionError, GatewaySessionManager
from surgical_contracts import (
    GatewayHandshake, GatewayHeartbeat, GatewayHello, GatewayStateFrame,
    LinkState, hello_auth_tag,
)
from tests.fakes.huayan_controller import datasheet_document, datasheet_frame

SECRET = b"step5-test-only-shared-secret-32-bytes!!"
DIGEST = "a" * 64
DEVICE_SN = "FAKE-E05-001"
MODEL = "E05-Pro"
VERSION = "6.3.6.20240305"


def manager(clock: list[int]) -> GatewaySessionManager:
    return GatewaySessionManager(
        secret=SECRET,
        gateway_id="mac-edge-test",
        device_sn=DEVICE_SN,
        robot_model=MODEL,
        package_versions=(VERSION,),
        config_sha256=DIGEST,
        stale_ms=250,
        gateway_timeout_ms=1000,
        transit_budget_ms=10,
        clock_ns=lambda: clock[0],
    )


def hello(
    challenge: str, *, session_id: str | None = None, secret: bytes = SECRET,
    config_sha256: str = DIGEST,
) -> GatewayHello:
    handshake = GatewayHandshake(
        gateway_session_id=session_id or secrets.token_hex(16),
        device_sn=DEVICE_SN,
        robot_model=MODEL,
        package_version=VERSION,
        safety_config_sha256=config_sha256,
    )
    return GatewayHello(
        gateway_id="mac-edge-test",
        challenge=challenge,
        handshake=handshake,
        auth_tag=hello_auth_tag(
            secret, gateway_id="mac-edge-test", challenge=challenge, handshake=handshake,
        ),
    )


def state_frame(
    session_id: str, *, message_sequence: int = 1, source_sequence: int = 1,
    command_connected: bool = True,
):
    sample = DatasheetFrameDecoder(byte_order="little").feed(
        datasheet_frame(datasheet_document())
    )[0]
    sample = sample.__class__(**{**sample.__dict__, "received_wall_ms": 1})
    watchdog = StateWatchdog(stale_ms=250, clock_ns=lambda: sample.received_monotonic_ns + 5_000_000)
    telemetry = telemetry_from_sample(
        SampleRecord(source_sequence, sample),
        session_id=session_id,
        device_sn=DEVICE_SN,
        robot_model=MODEL,
        package_version=VERSION,
        controller_is_simulation=False,
        command_connected=command_connected,
        watchdog=watchdog,
    )
    return GatewayStateFrame(
        gateway_session_id=session_id,
        message_sequence=message_sequence,
        state=telemetry,
    )


def test_authentication_single_owner_sequence_and_old_session_rejection() -> None:
    clock = [1_000_000_000]
    sessions = manager(clock)
    challenge = sessions.new_challenge()
    first = hello(challenge)
    with pytest.raises(GatewaySessionError, match="authentication"):
        sessions.open(hello(challenge, secret=b"wrong" * 8), challenge=challenge, connection_key="bad")
    sessions.open(first, challenge=challenge, connection_key="socket-1")
    second_challenge = sessions.new_challenge()
    with pytest.raises(GatewaySessionError, match="another"):
        sessions.open(hello(second_challenge), challenge=second_challenge, connection_key="socket-2")
    frame = state_frame(first.handshake.gateway_session_id)
    sessions.ingest_state(frame, connection_key="socket-1")
    assert sessions.health().status == "healthy"
    assert sessions.telemetry().joint_positions_deg is not None
    with pytest.raises(GatewaySessionError, match="duplicate"):
        sessions.ingest_state(frame, connection_key="socket-1")
    sessions.disconnect(connection_key="socket-1")
    with pytest.raises(GatewaySessionError, match="inactive"):
        sessions.ingest_state(state_frame(first.handshake.gateway_session_id, message_sequence=2), connection_key="socket-1")
    with pytest.raises(GatewaySessionError, match="already used"):
        sessions.open(first, challenge=challenge, connection_key="socket-3")
    new_challenge = sessions.new_challenge()
    second = hello(new_challenge)
    sessions.open(second, challenge=new_challenge, connection_key="socket-4")
    assert sessions.health().error == "datasheet_disconnected"


def test_stale_command_disconnect_and_gateway_lease_expiry() -> None:
    clock = [1_000_000_000]
    sessions = manager(clock)
    challenge = sessions.new_challenge()
    greeting = hello(challenge)
    sessions.open(greeting, challenge=challenge, connection_key="socket")
    sessions.ingest_state(state_frame(greeting.handshake.gateway_session_id), connection_key="socket")
    clock[0] += 300_000_000
    assert sessions.health().error == "datasheet_stale"
    sessions.ingest_heartbeat(GatewayHeartbeat(
        gateway_session_id=greeting.handshake.gateway_session_id,
        message_sequence=2,
        datasheet=LinkState.CONNECTED,
        command_socket=LinkState.DISCONNECTED,
    ), connection_key="socket")
    sessions.ingest_state(state_frame(
        greeting.handshake.gateway_session_id, message_sequence=3, source_sequence=2,
        command_connected=False,
    ), connection_key="socket")
    assert sessions.health().error == "command_socket_disconnected"
    clock[0] += 1_100_000_000
    assert sessions.health().error == "gateway_disconnected"
    with pytest.raises(GatewaySessionError, match="inactive"):
        sessions.ingest_heartbeat(GatewayHeartbeat(
            gateway_session_id=greeting.handshake.gateway_session_id,
            message_sequence=4,
            datasheet=LinkState.CONNECTED,
            command_socket=LinkState.CONNECTED,
        ), connection_key="socket")


def test_server_restart_requires_a_new_challenge_and_session() -> None:
    clock = [1_000_000_000]
    before_restart = manager(clock)
    old_challenge = before_restart.new_challenge()
    old_hello = hello(old_challenge)
    before_restart.open(old_hello, challenge=old_challenge, connection_key="old-socket")
    before_restart.ingest_state(
        state_frame(old_hello.handshake.gateway_session_id), connection_key="old-socket",
    )

    after_restart = manager(clock)
    new_challenge = after_restart.new_challenge()
    with pytest.raises(GatewaySessionError, match="authentication"):
        after_restart.open(old_hello, challenge=new_challenge, connection_key="old-socket")
    assert after_restart.health().error == "gateway_disconnected"

    new_hello = hello(new_challenge)
    after_restart.open(new_hello, challenge=new_challenge, connection_key="new-socket")
    assert new_hello.handshake.gateway_session_id != old_hello.handshake.gateway_session_id
    assert after_restart.health().error == "datasheet_disconnected"
    assert after_restart.health().ready_for_motion is False
