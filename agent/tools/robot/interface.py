"""Abstraction shared by simulated and future real robot controllers."""

from typing import Protocol, runtime_checkable

from surgical_contracts import (
    MoveRelativeRequest,
    MoveRelativeResult,
    MoveToEntryRequest,
    MoveToEntryResult,
    RobotState,
)


@runtime_checkable
class RobotController(Protocol):
    """High-level robot operations available to the deterministic runtime."""

    def get_state(self) -> RobotState:
        """Return current state without producing motion."""

        ...

    def move_to_entry(self, request: MoveToEntryRequest) -> MoveToEntryResult:
        """Move the configured TCP to an entry point."""

        ...

    def move_relative(self, request: MoveRelativeRequest) -> MoveRelativeResult:
        """Move the configured TCP by a Cartesian translation."""

        ...

    def stop(self, command_id: str | None = None) -> RobotState:
        """Stop normal motion and return the resulting state."""

        ...

    def emergency_stop(self, command_id: str | None = None) -> RobotState:
        """Latch an emergency stop and return the resulting state."""

        ...

    def reset_estop(self, command_id: str | None = None) -> RobotState:
        """Explicitly clear a previously latched emergency stop."""

        ...
