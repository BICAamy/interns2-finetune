"""Conservative mapping of documented vendor failures (2026-01-08 list)."""

from __future__ import annotations

import hashlib

from surgical_contracts import ErrorCode, ExecutionCertainty, FaultRecoverability, VendorFault

from .models import CommandReply

_KNOWN: dict[int, tuple[ErrorCode | None, FaultRecoverability]] = {
    20004: (ErrorCode.COMMAND_CONFLICT, FaultRecoverability.RETRY_AFTER_STATE_CHANGE),
    20005: (ErrorCode.INVALID_COMMAND_SCHEMA, FaultRecoverability.OPERATOR_ACTION),
    20006: (ErrorCode.INVALID_COMMAND_SCHEMA, FaultRecoverability.OPERATOR_ACTION),
    20007: (ErrorCode.INVALID_COMMAND_SCHEMA, FaultRecoverability.OPERATOR_ACTION),
    20008: (ErrorCode.COMMAND_CONFLICT, FaultRecoverability.RETRY_AFTER_STATE_CHANGE),
    20012: (ErrorCode.OPERATION_NOT_ENABLED, FaultRecoverability.OPERATOR_ACTION),
    20018: (ErrorCode.OPERATION_NOT_ENABLED, FaultRecoverability.RETRY_AFTER_STATE_CHANGE),
    20020: (ErrorCode.OPERATION_NOT_ENABLED, FaultRecoverability.OPERATOR_ACTION),
    # These have no exact shared error code yet. Keep the vendor code intact.
    20021: (None, FaultRecoverability.OPERATOR_ACTION),  # self-collision risk
    20029: (None, FaultRecoverability.OPERATOR_ACTION),  # TCP missing
    20030: (None, FaultRecoverability.OPERATOR_ACTION),  # UCS missing
    20035: (None, FaultRecoverability.OPERATOR_ACTION),  # socket disconnected
    20057: (ErrorCode.ESTOP_ACTIVE, FaultRecoverability.OPERATOR_ACTION),
}


def vendor_fault(reply: CommandReply, *, raw_response: bytes | None = None) -> VendorFault:
    """Classify a Fail reply; recoverability never authorizes an automatic retry."""
    if reply.vendor_error_code is None:
        raise ValueError("successful replies have no vendor fault")
    stable, recovery = _KNOWN.get(
        reply.vendor_error_code,
        (None, FaultRecoverability.UNKNOWN),
    )
    return VendorFault(
        vendor_error_code=reply.vendor_error_code,
        vendor_error_message=reply.vendor_error_message,
        stable_error_code=stable,
        recoverability=recovery,
        execution_certainty=ExecutionCertainty.REJECTED,
        raw_response_digest=(
            hashlib.sha256(raw_response).hexdigest() if raw_response is not None else None
        ),
    )
