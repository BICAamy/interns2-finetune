"""Abstraction for the external puncture path-planning tool."""

from typing import Protocol, runtime_checkable

from surgical_contracts import PlanPunctureRequest, PlanPunctureResult


@runtime_checkable
class PuncturePlannerClient(Protocol):
    def plan(self, request: PlanPunctureRequest) -> PlanPunctureResult:
        """Return a versioned, non-executable planning result envelope."""

        ...
