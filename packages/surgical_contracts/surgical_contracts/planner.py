"""External puncture-planner request and result envelopes."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .coordinates import Point3D
from .errors import ErrorCode


class PlannerStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNAVAILABLE = "unavailable"


class PlanPunctureRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    entry_point: Point3D
    target_point: Point3D

    @model_validator(mode="after")
    def validate_points(self) -> "PlanPunctureRequest":
        if self.entry_point.frame != self.target_point.frame:
            raise ValueError("entry_point and target_point must use the same frame")
        if self.entry_point.distance_to(self.target_point) == 0:
            raise ValueError("entry_point and target_point must be different")
        return self


class PlanPunctureResult(ContractModel):
    """Version 1 only carries non-executable preview or external output data."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    request_id: str = Field(min_length=1, max_length=128)
    status: PlannerStatus
    planner_name: str = Field(min_length=1)
    planner_version: str = Field(min_length=1)
    output_schema_version: str = Field(min_length=1)
    control_mode: str | None = None
    control_payload: dict[str, Any] = Field(default_factory=dict)
    executable: Literal[False] = False
    message: str = Field(min_length=1)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "PlanPunctureResult":
        if self.status == PlannerStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful planner result cannot contain error_code")
        if self.status == PlannerStatus.SUCCESS and not self.control_mode:
            raise ValueError("successful planner result requires control_mode")
        if self.status == PlannerStatus.SUCCESS and not self.control_payload:
            raise ValueError("successful planner result requires control_payload")
        if self.status != PlannerStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success planner result requires error_code")
        return self


class PlannerHealth(ContractModel):
    """Stable health response exposed by the planner-adapter service."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    service: Literal["planner-adapter"] = "planner-adapter"
    status: Literal["healthy", "unhealthy"]
    ready: bool
    provider: str = Field(min_length=1)
    planner_version: str = Field(min_length=1)
    output_schema_version: str = Field(min_length=1)
    executable: Literal[False] = False
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_readiness(self) -> "PlannerHealth":
        if self.ready != (self.status == "healthy"):
            raise ValueError("healthy status and ready must agree")
        return self
