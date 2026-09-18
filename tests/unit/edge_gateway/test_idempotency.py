from __future__ import annotations

from edge_gateway.state_machine import RejectOnlyLedger
from surgical_contracts import (
    ErrorCode, GatewayCommandKind, RobotCommandEnvelope, SoftwareStopRequest,
)


def envelope(command_id: str = "stop-1", *, session_id: str = "a" * 32, sequence: int = 1):
    return RobotCommandEnvelope(
        gateway_session_id=session_id,
        command_id=command_id,
        command_kind=GatewayCommandKind.SOFTWARE_STOP_REQUEST,
        created_at_ms=1000,
        expires_at_ms=2000,
        based_on_robot_state_sequence=sequence,
        payload=SoftwareStopRequest(command_id=command_id),
    )


def test_mac_rejects_every_request_and_detects_id_conflicts() -> None:
    ledger = RejectOnlyLedger(max_records=2)
    first = ledger.reject(envelope(), active_session_id="a" * 32)
    assert first.error_code == ErrorCode.OPERATION_NOT_ENABLED
    assert ledger.reject(envelope(), active_session_id="a" * 32) == first
    conflict = ledger.reject(envelope(sequence=2), active_session_id="a" * 32)
    assert conflict.error_code == ErrorCode.COMMAND_CONFLICT
    old = ledger.reject(envelope("stop-2", session_id="b" * 32), active_session_id="a" * 32)
    assert old.error_code == ErrorCode.COMMAND_EXPIRED
    ledger.reject(envelope("stop-3"), active_session_id="a" * 32)
    assert len(ledger._records) == 2
