"""Deterministic mock provider; it contains no path-planning algorithm."""

from __future__ import annotations

from threading import Lock
from typing import Any

from surgical_contracts import ErrorCode, PlanPunctureRequest

from planner_adapter.config import MockPlannerOutcome

from .base import ProviderMetadata, ProviderOutput


class MockPuncturePlannerProvider:
    """Return endpoint-only preview data or configured fault responses."""

    def __init__(
        self,
        *,
        outcome: MockPlannerOutcome = MockPlannerOutcome.SUCCESS,
        output_schema_version: str = "preview-v1",
    ) -> None:
        self.outcome = outcome
        self._metadata = ProviderMetadata(
            name="mock",
            planner_version="mock-v1",
            output_schema_version=output_schema_version,
        )
        self._lock = Lock()
        self.calls: list[PlanPunctureRequest] = []

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    @property
    def ready(self) -> bool:
        return True

    @property
    def call_count(self) -> int:
        with self._lock:
            return len(self.calls)

    def plan(self, request: PlanPunctureRequest) -> ProviderOutput:
        with self._lock:
            self.calls.append(request.model_copy(deep=True))

        if self.outcome == MockPlannerOutcome.TIMEOUT:
            raise TimeoutError("Mock planner simulated a timeout")
        if self.outcome == MockPlannerOutcome.INVALID_SCHEMA:
            return self._invalid_schema(request)
        if self.outcome == MockPlannerOutcome.VERSION_MISMATCH:
            result = self._success(request)
            result["output_schema_version"] = "unsupported-preview-v999"
            return result
        if self.outcome == MockPlannerOutcome.FAILURE:
            return {
                "request_id": request.request_id,
                "status": "failed",
                "planner_name": self.metadata.name,
                "planner_version": self.metadata.planner_version,
                "output_schema_version": self.metadata.output_schema_version,
                "control_payload": {},
                "executable": False,
                "message": "Mock planner simulated a planning failure",
                "error_code": ErrorCode.INVALID_PLANNER_OUTPUT.value,
            }
        return self._success(request)

    def _success(self, request: PlanPunctureRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "status": "success",
            "planner_name": self.metadata.name,
            "planner_version": self.metadata.planner_version,
            "output_schema_version": self.metadata.output_schema_version,
            "control_mode": "mock_preview",
            "control_payload": {
                "preview_points_mm": [
                    list(request.entry_point.as_tuple()),
                    list(request.target_point.as_tuple()),
                ],
                "frame": request.entry_point.frame.value,
                "unit": request.entry_point.unit.value,
            },
            "executable": False,
            "message": (
                "Mock preview contains only the requested entry and target points; "
                "it is not a puncture trajectory"
            ),
        }

    def _invalid_schema(self, request: PlanPunctureRequest) -> dict[str, Any]:
        payload = self._success(request)
        payload.pop("planner_version")
        payload["unexpected_control_values"] = [1, 2, 3]
        return payload
