"""Provider-neutral planning service with strict output validation."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from surgical_contracts import (
    ErrorCode,
    PlannerHealth,
    PlannerStatus,
    PlanPunctureRequest,
    PlanPunctureResult,
)

from .config import PlannerAdapterSettings, PlannerProviderKind
from .providers import (
    ExternalPuncturePlannerProvider,
    MockPuncturePlannerProvider,
    PlannerProvider,
    ProviderUnavailableError,
)


def build_provider(settings: PlannerAdapterSettings) -> PlannerProvider:
    if settings.provider == PlannerProviderKind.MOCK:
        return MockPuncturePlannerProvider(
            outcome=settings.mock_outcome,
            output_schema_version=settings.expected_output_schema_version,
        )
    return ExternalPuncturePlannerProvider()


class PlannerAdapter:
    """Call one configured provider and enforce the stable internal contract."""

    def __init__(
        self,
        settings: PlannerAdapterSettings,
        provider: PlannerProvider | None = None,
    ) -> None:
        settings.validate()
        selected = provider or build_provider(settings)
        if not isinstance(selected, PlannerProvider):
            raise TypeError("provider does not implement PlannerProvider")
        self.settings = settings
        self.provider = selected

    def health(self) -> PlannerHealth:
        ready = self.provider.ready
        metadata = self.provider.metadata
        return PlannerHealth(
            status="healthy" if ready else "unhealthy",
            ready=ready,
            provider=metadata.name,
            planner_version=metadata.planner_version,
            output_schema_version=self.settings.expected_output_schema_version,
            executable=False,
            message=(
                "Planner adapter is ready"
                if ready
                else "Selected planner provider is not configured"
            ),
            details={
                "configured_provider": self.settings.provider.value,
                "mock_outcome": self.settings.mock_outcome.value,
                "provider_output_schema_version": metadata.output_schema_version,
                "request_timeout_s": self.settings.request_timeout_s,
            },
        )

    def plan(self, request: PlanPunctureRequest) -> PlanPunctureResult:
        if not self.provider.ready:
            return self._failure(
                request,
                status=PlannerStatus.UNAVAILABLE,
                error_code=ErrorCode.PLANNER_UNAVAILABLE,
                message="Selected planner provider is not configured",
            )

        try:
            raw_result = self.provider.plan(request)
        except TimeoutError:
            return self._failure(
                request,
                status=PlannerStatus.TIMED_OUT,
                error_code=ErrorCode.PLANNER_TIMEOUT,
                message="Planner provider timed out",
            )
        except (ProviderUnavailableError, ConnectionError):
            return self._failure(
                request,
                status=PlannerStatus.UNAVAILABLE,
                error_code=ErrorCode.PLANNER_UNAVAILABLE,
                message="Planner provider is unavailable",
            )
        except Exception as exc:  # pragma: no cover - defensive service boundary
            return self._failure(
                request,
                status=PlannerStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR,
                message=f"Planner provider failed with {type(exc).__name__}",
            )

        try:
            result = PlanPunctureResult.model_validate(raw_result)
        except ValidationError as exc:
            return self._failure(
                request,
                status=PlannerStatus.FAILED,
                error_code=ErrorCode.INVALID_PLANNER_OUTPUT,
                message=(
                    "Planner provider returned an invalid result schema "
                    f"({exc.error_count()} validation errors)"
                ),
            )

        mismatch = self._output_mismatch(request, result)
        if mismatch is not None:
            return self._failure(
                request,
                status=PlannerStatus.FAILED,
                error_code=ErrorCode.INVALID_PLANNER_OUTPUT,
                message=mismatch,
            )
        return result

    def _output_mismatch(
        self,
        request: PlanPunctureRequest,
        result: PlanPunctureResult,
    ) -> str | None:
        metadata = self.provider.metadata
        if result.request_id != request.request_id:
            return "Planner result request_id does not match the request"
        if result.planner_name != metadata.name:
            return "Planner result provider name does not match the selected provider"
        if result.planner_version != metadata.planner_version:
            return "Planner result version does not match provider metadata"
        if result.output_schema_version != self.settings.expected_output_schema_version:
            return (
                "Planner output schema version mismatch: expected "
                f"{self.settings.expected_output_schema_version}, got "
                f"{result.output_schema_version}"
            )
        if result.status == PlannerStatus.SUCCESS:
            if not result.control_mode:
                return "Successful planner result is missing control_mode"
            if not result.control_payload:
                return "Successful planner result is missing control_payload"
        return None

    def _failure(
        self,
        request: PlanPunctureRequest,
        *,
        status: PlannerStatus,
        error_code: ErrorCode,
        message: str,
    ) -> PlanPunctureResult:
        metadata = self.provider.metadata
        return PlanPunctureResult(
            request_id=request.request_id,
            status=status,
            planner_name=metadata.name,
            planner_version=metadata.planner_version,
            output_schema_version=self.settings.expected_output_schema_version,
            control_payload={},
            executable=False,
            message=message,
            error_code=error_code,
        )

    @staticmethod
    def is_unavailable(result: PlanPunctureResult) -> bool:
        return result.status == PlannerStatus.UNAVAILABLE

    @staticmethod
    def result_payload(result: PlanPunctureResult) -> dict[str, Any]:
        return result.model_dump(mode="json")
