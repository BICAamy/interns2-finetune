"""Deterministic planner fake used until the external tool is available."""

from __future__ import annotations

from enum import Enum

from surgical_contracts import (
    ErrorCode,
    PlanPunctureRequest,
    PlanPunctureResult,
    PlannerStatus,
)


class FakePlannerOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


class FakePuncturePlannerClient:
    """Record calls and return explicitly non-executable preview data."""

    def __init__(
        self,
        *,
        outcome: FakePlannerOutcome = FakePlannerOutcome.SUCCESS,
    ) -> None:
        self.outcome = outcome
        self.calls: list[PlanPunctureRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def plan(self, request: PlanPunctureRequest) -> PlanPunctureResult:
        self.calls.append(request.model_copy(deep=True))

        if self.outcome == FakePlannerOutcome.SUCCESS:
            return PlanPunctureResult(
                request_id=request.request_id,
                status=PlannerStatus.SUCCESS,
                planner_name="fake_puncture_planner",
                planner_version="fake-v1",
                output_schema_version="preview-v1",
                control_mode="mock_preview",
                control_payload={
                    "preview_points_mm": [
                        list(request.entry_point.as_tuple()),
                        list(request.target_point.as_tuple()),
                    ],
                    "frame": request.entry_point.frame.value,
                },
                executable=False,
                message="Fake planner produced preview data only",
            )

        if self.outcome == FakePlannerOutcome.TIMEOUT:
            return self._failure(
                request,
                PlannerStatus.TIMED_OUT,
                ErrorCode.PLANNER_TIMEOUT,
                "Fake planner timed out",
            )
        if self.outcome == FakePlannerOutcome.UNAVAILABLE:
            return self._failure(
                request,
                PlannerStatus.UNAVAILABLE,
                ErrorCode.PLANNER_UNAVAILABLE,
                "Fake planner is unavailable",
            )
        return self._failure(
            request,
            PlannerStatus.FAILED,
            ErrorCode.INVALID_PLANNER_OUTPUT,
            "Fake planner simulated a planning failure",
        )

    @staticmethod
    def _failure(
        request: PlanPunctureRequest,
        status: PlannerStatus,
        error_code: ErrorCode,
        message: str,
    ) -> PlanPunctureResult:
        return PlanPunctureResult(
            request_id=request.request_id,
            status=status,
            planner_name="fake_puncture_planner",
            planner_version="fake-v1",
            output_schema_version="preview-v1",
            executable=False,
            message=message,
            error_code=error_code,
        )
