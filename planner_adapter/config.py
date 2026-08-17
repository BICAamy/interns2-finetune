"""Environment-backed configuration for the planner-adapter service."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os


class PlannerProviderKind(str, Enum):
    MOCK = "mock"
    EXTERNAL = "external"


class MockPlannerOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    INVALID_SCHEMA = "invalid_schema"
    VERSION_MISMATCH = "version_mismatch"


def _as_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True)
class PlannerAdapterSettings:
    provider: PlannerProviderKind = PlannerProviderKind.MOCK
    mock_outcome: MockPlannerOutcome = MockPlannerOutcome.SUCCESS
    expected_output_schema_version: str = "preview-v1"
    request_timeout_s: float = 10.0
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> "PlannerAdapterSettings":
        settings = cls(
            provider=PlannerProviderKind(
                os.getenv("PLANNER_PROVIDER", PlannerProviderKind.MOCK.value).strip()
            ),
            mock_outcome=MockPlannerOutcome(
                os.getenv(
                    "PLANNER_MOCK_OUTCOME",
                    MockPlannerOutcome.SUCCESS.value,
                ).strip()
            ),
            expected_output_schema_version=os.getenv(
                "PLANNER_EXPECTED_OUTPUT_SCHEMA_VERSION",
                "preview-v1",
            ).strip(),
            request_timeout_s=_as_float("PLANNER_REQUEST_TIMEOUT", 10.0),
            host=os.getenv("PLANNER_ADAPTER_HOST", "0.0.0.0").strip(),
            port=_as_int("PLANNER_ADAPTER_PORT", 8002),
            log_level=os.getenv("PLANNER_ADAPTER_LOG_LEVEL", "info").strip(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.expected_output_schema_version:
            raise ValueError("PLANNER_EXPECTED_OUTPUT_SCHEMA_VERSION cannot be empty")
        if self.request_timeout_s <= 0:
            raise ValueError("PLANNER_REQUEST_TIMEOUT must be greater than zero")
        if not self.host:
            raise ValueError("PLANNER_ADAPTER_HOST cannot be empty")
        if not 1 <= self.port <= 65535:
            raise ValueError("PLANNER_ADAPTER_PORT must be between 1 and 65535")
        if not self.log_level:
            raise ValueError("PLANNER_ADAPTER_LOG_LEVEL cannot be empty")
