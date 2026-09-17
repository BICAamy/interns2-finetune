"""In-memory rejected-command records for the disconnected real stub only.

This is not a durable motion journal. A future executable real provider must
implement its own persistent idempotency and unknown-execution handling.
"""

from __future__ import annotations

import json
from threading import Lock
import time
from typing import Any

from surgical_contracts import (
    CommandExecutionStatus,
    ErrorCode,
    ErrorResponse,
    RobotCommandKind,
    RobotCommandRecord,
)

from .provider import RobotRuntimeServiceError


class RejectedCommandStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: dict[str, RobotCommandRecord] = {}
        self._fingerprints: dict[str, str] = {}

    def reject(
        self,
        kind: RobotCommandKind,
        request: Any,
        *,
        message: str = "Real robot gateway is disconnected; control is not enabled",
    ) -> tuple[RobotCommandRecord, bool]:
        payload = request.model_dump(mode="json")
        fingerprint = json.dumps(
            {"kind": kind.value, "request": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        command_id = request.command_id
        with self._lock:
            existing = self._records.get(command_id)
            if existing is not None:
                if self._fingerprints[command_id] != fingerprint:
                    raise RobotRuntimeServiceError(
                        ErrorCode.COMMAND_CONFLICT,
                        f"command_id {command_id!r} was already used with different arguments",
                        status_code=409,
                    )
                return existing.model_copy(deep=True), False
            timestamp = time.time_ns() // 1_000_000
            record = RobotCommandRecord(
                command_id=command_id,
                kind=kind,
                status=CommandExecutionStatus.REJECTED,
                submitted_at_ms=timestamp,
                updated_at_ms=timestamp,
                request=payload,
                error=ErrorResponse(
                    code=ErrorCode.OPERATION_NOT_ENABLED,
                    command_id=command_id,
                    message=message,
                ),
            )
            self._records[command_id] = record
            self._fingerprints[command_id] = fingerprint
            return record.model_copy(deep=True), True

    def get(self, command_id: str) -> RobotCommandRecord:
        with self._lock:
            record = self._records.get(command_id)
            if record is None:
                raise RobotRuntimeServiceError(
                    ErrorCode.COMMAND_NOT_FOUND,
                    f"unknown command_id: {command_id}",
                    status_code=404,
                )
            return record.model_copy(deep=True)
