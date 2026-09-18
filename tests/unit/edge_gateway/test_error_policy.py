from __future__ import annotations

import pytest

from edge_gateway.huayan.command_codec import decode_reply
from edge_gateway.huayan.error_policy import vendor_fault
from edge_gateway.huayan.models import ReadCommand
from surgical_contracts import ErrorCode, ExecutionCertainty, FaultRecoverability


def test_known_vendor_failure_keeps_code_and_never_claims_motion_completed() -> None:
    raw = b"ReadCurFSM,Fail,20018,command forbidden in this state,;"
    reply = decode_reply(raw, expected=ReadCommand.CURRENT_FSM)
    fault = vendor_fault(reply, raw_response=raw)
    assert fault.vendor_error_code == 20018
    assert fault.stable_error_code == ErrorCode.OPERATION_NOT_ENABLED
    assert fault.execution_certainty == ExecutionCertainty.REJECTED
    assert fault.raw_response_digest and len(fault.raw_response_digest) == 64


def test_unknown_vendor_failure_fails_closed_without_guessed_recovery() -> None:
    reply = decode_reply(b"ReadCurFSM,Fail,99999,unknown,;", expected=ReadCommand.CURRENT_FSM)
    fault = vendor_fault(reply)
    assert fault.vendor_error_code == 99999
    assert fault.stable_error_code is None
    assert fault.recoverability == FaultRecoverability.UNKNOWN
    with pytest.raises(ValueError):
        vendor_fault(decode_reply(b"ReadCurFSM,OK,33,;", expected=ReadCommand.CURRENT_FSM))
