"""Deterministic orchestration primitives for the surgical agent."""

from .command_arbiter import CommandCandidate, CommandSource, choose_command
from .orchestrator import (
    OrchestrationPolicy,
    OrchestrationResult,
    SurgicalTaskOrchestrator,
)
from .runtime_events import RuntimeEvent, build_runtime_events
from .state_machine import (
    AgentTaskState,
    InvalidStateTransition,
    StateTransitionEvent,
    TaskStateMachine,
)

__all__ = [
    "AgentTaskState",
    "CommandCandidate",
    "CommandSource",
    "InvalidStateTransition",
    "OrchestrationPolicy",
    "OrchestrationResult",
    "RuntimeEvent",
    "StateTransitionEvent",
    "SurgicalTaskOrchestrator",
    "TaskStateMachine",
    "build_runtime_events",
    "choose_command",
]
