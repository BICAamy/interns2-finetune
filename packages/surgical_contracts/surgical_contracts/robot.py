"""Robot state, command, and result contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, FiniteFloat, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .coordinates import CoordinateFrame, Point3D
from .errors import ErrorCode


class RuntimeMode(str, Enum):
    SIMULATION = "simulation"
    REAL = "real"


class MotionState(str, Enum):
    IDLE = "idle"
    MOVING = "moving"
    AT_ENTRY = "at_entry"
    STOPPED = "stopped"
    ESTOP = "estop"
    FAILED = "failed"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class RobotState(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    mode: RuntimeMode = RuntimeMode.SIMULATION
    tcp: str = Field(default="needle_tip", min_length=1)
    tcp_position: Point3D
    orientation_xyzw: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] = (
        0.0,
        0.0,
        0.0,
        1.0,
    )
    motion_state: MotionState = MotionState.IDLE
    estop: bool = False
    active_command_id: str | None = Field(default=None, min_length=1, max_length=128)


class MoveToEntryRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    entry_point: Point3D
    tcp: str = Field(default="needle_tip", min_length=1)
    orientation_policy: str = Field(
        default="configured_safe_orientation",
        min_length=1,
    )
    speed_mm_s: FiniteFloat = Field(default=5.0, gt=0)


class MoveToEntryResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    status: ToolStatus
    reached: bool
    final_tcp_position: Point3D
    position_error_mm: FiniteFloat | None = Field(default=None, ge=0)
    trajectory_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "MoveToEntryResult":
        if self.status == ToolStatus.SUCCESS and not self.reached:
            raise ValueError("successful move-to-entry result must have reached=true")
        if self.status == ToolStatus.SUCCESS and self.position_error_mm is None:
            raise ValueError("successful move-to-entry result requires position_error_mm")
        if self.status == ToolStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful move-to-entry result cannot contain error_code")
        if self.status != ToolStatus.SUCCESS and self.reached:
            raise ValueError("failed move-to-entry result cannot have reached=true")
        if self.status != ToolStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success move-to-entry result requires error_code")
        return self


class MoveRelativeRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    translation_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    speed_mm_s: FiniteFloat = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def validate_translation(self) -> "MoveRelativeRequest":
        if all(float(value) == 0.0 for value in self.translation_mm):
            raise ValueError("translation_mm cannot be the zero vector")
        return self


class MoveRelativeResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    status: ToolStatus
    completed: bool
    final_tcp_position: Point3D
    trajectory_id: str | None = Field(default=None, min_length=1, max_length=128)
    message: str = Field(min_length=1)
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def validate_status(self) -> "MoveRelativeResult":
        if self.status == ToolStatus.SUCCESS and not self.completed:
            raise ValueError("successful relative movement must have completed=true")
        if self.status == ToolStatus.SUCCESS and self.error_code is not None:
            raise ValueError("successful relative movement cannot contain error_code")
        if self.status != ToolStatus.SUCCESS and self.completed:
            raise ValueError("failed relative movement cannot have completed=true")
        if self.status != ToolStatus.SUCCESS and self.error_code is None:
            raise ValueError("non-success relative movement requires error_code")
        return self
