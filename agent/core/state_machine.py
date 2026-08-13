"""Small explicit state machine used by the Step 2 mock orchestrator."""

from __future__ import annotations

from enum import Enum


class AgentTaskState(str, Enum):
    IDLE = "idle"
    VALIDATING = "validating"
    CLARIFICATION_REQUIRED = "clarification_required"
    EXECUTING_RELATIVE = "executing_relative"
    MOVING_TO_ENTRY = "moving_to_entry"
    AT_ENTRY = "at_entry"
    PATH_PLANNING = "path_planning"
    PLAN_READY = "plan_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    ESTOP = "estop"


class InvalidStateTransition(RuntimeError):
    pass


_ALLOWED_TRANSITIONS: dict[AgentTaskState, set[AgentTaskState]] = {
    AgentTaskState.IDLE: {AgentTaskState.VALIDATING},
    AgentTaskState.VALIDATING: {
        AgentTaskState.CLARIFICATION_REQUIRED,
        AgentTaskState.EXECUTING_RELATIVE,
        AgentTaskState.MOVING_TO_ENTRY,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
        AgentTaskState.FAILED,
    },
    AgentTaskState.CLARIFICATION_REQUIRED: {AgentTaskState.COMPLETED},
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
        AgentTaskState.PLAN_READY,
        AgentTaskState.FAILED,
        AgentTaskState.STOPPED,
        AgentTaskState.ESTOP,
    },
    AgentTaskState.PLAN_READY: {AgentTaskState.COMPLETED},
    AgentTaskState.COMPLETED: set(),
    AgentTaskState.FAILED: set(),
    AgentTaskState.STOPPED: set(),
    AgentTaskState.ESTOP: set(),
}


class TaskStateMachine:
    """Track and validate the state history for one command."""

    def __init__(self) -> None:
        self._state = AgentTaskState.IDLE
        self._history = [self._state]

    @property
    def state(self) -> AgentTaskState:
        return self._state

    @property
    def history(self) -> tuple[AgentTaskState, ...]:
        return tuple(self._history)

    def transition(self, next_state: AgentTaskState) -> None:
        if next_state not in _ALLOWED_TRANSITIONS[self._state]:
            raise InvalidStateTransition(
                f"Cannot transition from {self._state.value} to {next_state.value}"
            )
        self._state = next_state
        self._history.append(next_state)
