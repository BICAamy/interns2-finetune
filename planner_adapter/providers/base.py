"""Stable provider protocol hidden behind the planner-adapter HTTP API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from surgical_contracts import PlanPunctureRequest, PlanPunctureResult


ProviderOutput = Mapping[str, Any] | PlanPunctureResult


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    planner_version: str
    output_schema_version: str

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.name,
                self.planner_version,
                self.output_schema_version,
            )
        ):
            raise ValueError("provider metadata values cannot be empty")


class ProviderUnavailableError(RuntimeError):
    """Raised when the selected provider cannot accept planning requests."""


@runtime_checkable
class PlannerProvider(Protocol):
    @property
    def metadata(self) -> ProviderMetadata:
        ...

    @property
    def ready(self) -> bool:
        ...

    def plan(self, request: PlanPunctureRequest) -> ProviderOutput:
        ...
