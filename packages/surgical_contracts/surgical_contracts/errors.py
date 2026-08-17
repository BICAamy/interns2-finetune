"""Stable error codes returned across service boundaries."""

from enum import Enum
from typing import Any

from pydantic import Field

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion


class ErrorCode(str, Enum):
    INVALID_COMMAND_SCHEMA = "INVALID_COMMAND_SCHEMA"
    MISSING_ENTRY_POINT = "MISSING_ENTRY_POINT"
    MISSING_TARGET_POINT = "MISSING_TARGET_POINT"
    INVALID_COORDINATE_FRAME = "INVALID_COORDINATE_FRAME"
    INVALID_UNIT = "INVALID_UNIT"
    OUT_OF_WORKSPACE = "OUT_OF_WORKSPACE"
    IK_FAILED = "IK_FAILED"
    ENTRY_NOT_REACHED = "ENTRY_NOT_REACHED"
    POSITION_TOLERANCE_EXCEEDED = "POSITION_TOLERANCE_EXCEEDED"
    ROBOT_TIMEOUT = "ROBOT_TIMEOUT"
    PLANNER_UNAVAILABLE = "PLANNER_UNAVAILABLE"
    PLANNER_TIMEOUT = "PLANNER_TIMEOUT"
    INVALID_PLANNER_OUTPUT = "INVALID_PLANNER_OUTPUT"
    ESTOP_ACTIVE = "ESTOP_ACTIVE"
    COMMAND_EXPIRED = "COMMAND_EXPIRED"
    OPERATION_NOT_ENABLED = "OPERATION_NOT_ENABLED"
    COMMAND_CONFLICT = "COMMAND_CONFLICT"
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_NO_TOOL_CALL = "MODEL_NO_TOOL_CALL"
    MODEL_INVALID_OUTPUT = "MODEL_INVALID_OUTPUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorResponse(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    code: ErrorCode
    message: str = Field(min_length=1)
    command_id: str | None = Field(default=None, min_length=1, max_length=128)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    details: dict[str, Any] = Field(default_factory=dict)
