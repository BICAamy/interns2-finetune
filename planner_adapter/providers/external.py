"""Intentional placeholder for the senior team's future planner integration."""

from __future__ import annotations

from surgical_contracts import PlanPunctureRequest

from .base import ProviderMetadata, ProviderOutput, ProviderUnavailableError


class ExternalPuncturePlannerProvider:
    """Declare the boundary without guessing transport or payload formats."""

    _metadata = ProviderMetadata(
        name="external",
        planner_version="unconfigured",
        output_schema_version="unconfigured",
    )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def ready(self) -> bool:
        return False

    def plan(self, request: PlanPunctureRequest) -> ProviderOutput:
        del request
        raise ProviderUnavailableError(
            "External planner is not configured; its transport and schema remain undefined"
        )
