"""Observe-only Mac state and bounded rejection/idempotency memory."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import Enum
from threading import RLock

from surgical_contracts import (
    ErrorCode,
    GatewayAcknowledgementStatus,
    RobotCommandAcknowledgement,
    RobotCommandEnvelope,
)

from .huayan.models import DatasheetSample


class EdgeMode(str, Enum):
    DISCONNECTED = "disconnected"
    OBSERVE_ONLY = "observe-only"
    DEGRADED = "degraded"
    FAULT = "fault"


@dataclass(frozen=True)
class SampleRecord:
    sequence: int
    sample: DatasheetSample


class EdgeState:
    """A one-slot pose buffer plus a bounded, non-dropping alert queue."""

    def __init__(self, *, max_events: int = 256) -> None:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        self._lock = RLock()
        self._latest: SampleRecord | None = None
        self._events: deque[SampleRecord] = deque()
        self._max_events = max_events
        self._sequence = 0
        self.cloud_connected = False
        self.command_connected = False
        self.datasheet_connected = False
        self.fault = False
        self.session_id: str | None = None

    @property
    def mode(self) -> EdgeMode:
        with self._lock:
            if self.fault:
                return EdgeMode.FAULT
            if not self.cloud_connected:
                return EdgeMode.DISCONNECTED
            if not self.command_connected or not self.datasheet_connected:
                return EdgeMode.DEGRADED
            return EdgeMode.OBSERVE_ONLY

    @property
    def motion_enabled(self) -> bool:
        return False

    def start_cloud_session(self, session_id: str) -> None:
        with self._lock:
            self.cloud_connected = True
            self.session_id = session_id

    def cloud_lost(self) -> None:
        with self._lock:
            self.cloud_connected = False
            self.session_id = None

    def observe(self, sample: DatasheetSample) -> SampleRecord:
        with self._lock:
            self._sequence += 1
            record = SampleRecord(self._sequence, sample)
            previous = self._latest.sample if self._latest else None
            changed = previous is None or (
                previous.fsm_code, previous.enabled, previous.moving,
                previous.paused, previous.error_code, previous.error_axis,
            ) != (
                sample.fsm_code, sample.enabled, sample.moving,
                sample.paused, sample.error_code, sample.error_axis,
            )
            if changed or sample.error_code or any(sample.axis_error_codes):
                if len(self._events) >= self._max_events:
                    self.fault = True
                    raise RuntimeError("edge alert queue full; refusing to discard safety changes")
                self._events.append(record)
            self._latest = record
            self.datasheet_connected = True
            return record

    def snapshot(self) -> tuple[SampleRecord | None, tuple[SampleRecord, ...]]:
        with self._lock:
            return self._latest, tuple(self._events)

    def acknowledged_through(self, sequence: int) -> None:
        with self._lock:
            while self._events and self._events[0].sequence <= sequence:
                self._events.popleft()


class RejectOnlyLedger:
    """No command can be accepted in Step 5; duplicate IDs remain deterministic."""

    def __init__(self, *, max_records: int = 1024) -> None:
        if max_records < 1:
            raise ValueError("max_records must be positive")
        self._lock = RLock()
        self._max_records = max_records
        self._records: OrderedDict[str, tuple[str, RobotCommandAcknowledgement]] = OrderedDict()

    def reject(self, envelope: RobotCommandEnvelope, *, active_session_id: str | None) -> RobotCommandAcknowledgement:
        canonical = json.dumps(envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._lock:
            existing = self._records.get(envelope.command_id)
            if existing is not None:
                code = (
                    existing[1].error_code if existing[0] == fingerprint
                    else ErrorCode.COMMAND_CONFLICT
                )
            else:
                code = (
                    ErrorCode.OPERATION_NOT_ENABLED
                    if envelope.gateway_session_id == active_session_id and active_session_id is not None
                    else ErrorCode.COMMAND_EXPIRED
                )
            result = RobotCommandAcknowledgement(
                gateway_session_id=envelope.gateway_session_id,
                command_id=envelope.command_id,
                status=GatewayAcknowledgementStatus.REJECTED,
                error_code=code,
            )
            if existing is None:
                self._records[envelope.command_id] = (fingerprint, result)
                if len(self._records) > self._max_records:
                    self._records.popitem(last=False)
            return result
