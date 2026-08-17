"""Explicit task state machine for deterministic surgical-tool orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import time
from typing import Callable


class AgentTaskState(str, Enum):
    IDLE = "idle"
    PARSING = "parsing"
    VALIDATING = "validating"
    CLARIFICATION_REQUIRED = "clarification_required"
    EXECUTING_RELATIVE = "executing_relative"
    MOVING_TO_ENTRY = "moving_to_entry"
    AT_ENTRY = "at_entry"
    PATH_PLANNING = "path_planning"
    PLANNER_UNAVAILABLE = "planner_unavailable"
    PLAN_FAILED = "plan_failed"
    PLAN_READY = "plan_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    ESTOP = "estop"


class InvalidStateTransition(RuntimeError):
    pass


@dataclass(frozen=True)
class StateTransitionEvent:
    """Auditable record of one accepted transition."""

    sequence: int
    from_state: AgentTaskState
    to_state: AgentTaskState
    timestamp_ms: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "sequence": self.sequence,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp_ms": self.timestamp_ms,
        }


_ALLOWED_TRANSITIONS: dict[AgentTaskState, set[AgentTaskState]] = {
    AgentTaskState.IDLE: {AgentTaskState.PARSING, AgentTaskState.ESTOP},
    AgentTaskState.PARSING: {
        AgentTaskState.VALIDATING,
        AgentTaskState.FAILED,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.VALIDATING: {
        AgentTaskState.CLARIFICATION_REQUIRED,
        AgentTaskState.EXECUTING_RELATIVE,
        AgentTaskState.MOVING_TO_ENTRY,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
        AgentTaskState.FAILED,
    },
    AgentTaskState.CLARIFICATION_REQUIRED: set(),
    AgentTaskState.EXECUTING_RELATIVE: {
        AgentTaskState.COMPLETED,
        AgentTaskState.FAILED,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.MOVING_TO_ENTRY: {
        AgentTaskState.AT_ENTRY,
        AgentTaskState.FAILED,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.AT_ENTRY: {
        AgentTaskState.COMPLETED,
        AgentTaskState.PATH_PLANNING,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.PATH_PLANNING: {
        AgentTaskState.PLANNER_UNAVAILABLE,
        AgentTaskState.PLAN_FAILED,
        AgentTaskState.PLAN_READY,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.PLANNER_UNAVAILABLE: set(),
    AgentTaskState.PLAN_FAILED: set(),
    AgentTaskState.PLAN_READY: set(),
    AgentTaskState.COMPLETED: set(),
    AgentTaskState.FAILED: set(),
    AgentTaskState.STOPPED: set(),
    AgentTaskState.ESTOP: set(),
}


class TaskStateMachine:
    """Track, validate, and timestamp the state history for one command."""

    def __init__(self, *, clock_ms: Callable[[], int] | None = None) -> None:
        self._state = AgentTaskState.IDLE
        self._history = [self._state]
        self._events: list[StateTransitionEvent] = []
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    @property
    def state(self) -> AgentTaskState:
        return self._state

    @property
    def history(self) -> tuple[AgentTaskState, ...]:
        return tuple(self._history)

    @property
    def events(self) -> tuple[StateTransitionEvent, ...]:
        return tuple(self._events)

    def transition(self, next_state: AgentTaskState) -> None:
        if next_state not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidStateTransition(
                f"Cannot transition from {self._state.value} to {next_state.value}"
            )
        previous = self._state
        self._state = next_state
        self._history.append(next_state)
        self._events.append(
            StateTransitionEvent(
                sequence=len(self._events) + 1,
                from_state=previous,
                to_state=next_state,
                timestamp_ms=self._clock_ms(),
            )
        )
