"""Thread-safe session state with revision-based WebSocket observation."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
import time
from typing import Any, Callable
from uuid import uuid4

from surgical_contracts import ParsedCommand, ToolEvent, ToolName

from ..asr import TranscriptionResult
from ..models import InputSource, STATUS_LABELS, SessionSnapshot, SessionStatus


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


class SessionNotFound(KeyError):
    pass


class SessionConflict(RuntimeError):
    pass


@dataclass
class SessionRecord:
    session_id: str
    created_at_ms: int
    updated_at_ms: int
    revision: int = 1
    status: SessionStatus = SessionStatus.READY
    prompt: str | None = None
    input_source: InputSource = InputSource.TEXT
    image_name: str | None = None
    asr_transcription: TranscriptionResult | None = None
    pending_command: ParsedCommand | None = None
    active_command_id: str | None = None
    raw_model_output: dict[str, Any] | None = None
    normalized_command: dict[str, Any] | None = None
    current_tcp: dict[str, Any] | None = None
    execution_events: list[dict[str, Any]] = field(default_factory=list)
    live_tool_events: list[dict[str, Any]] = field(default_factory=list)
    orchestration: dict[str, Any] | None = None
    message: str = ""
    error: dict[str, Any] | None = None
    parse_started_ms: int | None = None
    parse_finished_ms: int | None = None
    parse_token: str | None = None

    def snapshot(self) -> SessionSnapshot:
        timeline = self.execution_events or self.live_tool_events
        return SessionSnapshot(
            session_id=self.session_id,
            revision=self.revision,
            status=self.status,
            status_label=STATUS_LABELS[self.status],
            created_at_ms=self.created_at_ms,
            updated_at_ms=self.updated_at_ms,
            prompt=self.prompt,
            input_source=self.input_source,
            image_name=self.image_name,
            asr_transcription=self.asr_transcription,
            pending_confirmation=self.pending_command is not None,
            active_command_id=self.active_command_id,
            raw_model_output=self.raw_model_output,
            normalized_command=self.normalized_command,
            current_tcp=self.current_tcp,
            execution_events=list(timeline),
            orchestration=self.orchestration,
            message=self.message,
            error=self.error,
        )


class SessionStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, SessionRecord] = {}
        self._command_sessions: dict[str, str] = {}

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def create(self) -> SessionSnapshot:
        now = _now_ms()
        record = SessionRecord(
            session_id=f"session-{uuid4().hex}",
            created_at_ms=now,
            updated_at_ms=now,
        )
        with self._lock:
            self._records[record.session_id] = record
            return record.snapshot()

    def snapshot(self, session_id: str) -> SessionSnapshot:
        with self._lock:
            return self._get(session_id).snapshot()

    def mutate(
        self,
        session_id: str,
        operation: Callable[[SessionRecord], None],
    ) -> SessionSnapshot:
        with self._lock:
            record = self._get(session_id)
            operation(record)
            record.revision += 1
            record.updated_at_ms = _now_ms()
            return record.snapshot()

    def bind_command(self, session_id: str, command_id: str) -> None:
        with self._lock:
            self._get(session_id)
            self._command_sessions[command_id] = session_id

    def unbind_command(self, command_id: str) -> None:
        with self._lock:
            self._command_sessions.pop(command_id, None)

    def add_tool_event(self, event: ToolEvent) -> None:
        with self._lock:
            session_id = self._command_sessions.get(event.command_id)
            if session_id is None:
                return
            record = self._records.get(session_id)
            if record is None:
                return
            record.live_tool_events.append(event.model_dump(mode="json"))
            if event.tool == ToolName.ROBOT_MOVE_TO_ENTRY:
                record.status = (
                    SessionStatus.MOVING_TO_ENTRY
                    if event.phase.value == "started"
                    else SessionStatus.VERIFYING_ENTRY
                )
            elif event.tool == ToolName.ROBOT_MOVE_RELATIVE:
                record.status = SessionStatus.MOVING_RELATIVE
            elif event.tool == ToolName.PLANNER_PLAN_PUNCTURE:
                record.status = SessionStatus.PLANNING
            record.revision += 1
            record.updated_at_ms = _now_ms()

    def _get(self, session_id: str) -> SessionRecord:
        record = self._records.get(session_id)
        if record is None:
            raise SessionNotFound(session_id)
        return record
