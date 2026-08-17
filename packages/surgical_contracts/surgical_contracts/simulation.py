"""Versioned contracts exposed by the robot-simulation service."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, FiniteFloat, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .errors import ErrorResponse
from .robot import RobotState, ToolStatus


class RobotCommandKind(str, Enum):
    RESET = "reset"
    MOVE_TO_ENTRY = "move_to_entry"
    MOVE_RELATIVE = "move_relative"
    STOP = "stop"
    ESTOP = "estop"


class CameraControlAction(str, Enum):
    ORBIT = "orbit"
    ZOOM = "zoom"
    PAN = "pan"
    PRESET = "preset"


class CameraPreset(str, Enum):
    FRONT = "front"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    ISOMETRIC = "isometric"


class SimulationCameraControlRequest(ContractModel):
    """A bounded, view-only update for the shared SOFA camera."""

    schema_version: SchemaVersion = SCHEMA_VERSION
    action: CameraControlAction
    yaw_delta_deg: FiniteFloat | None = Field(default=None, ge=-30.0, le=30.0)
    pitch_delta_deg: FiniteFloat | None = Field(default=None, ge=-30.0, le=30.0)
    distance_delta_m: FiniteFloat | None = Field(default=None, ge=-0.4, le=0.4)
    pan_right_delta_m: FiniteFloat | None = Field(default=None, ge=-0.2, le=0.2)
    pan_up_delta_m: FiniteFloat | None = Field(default=None, ge=-0.2, le=0.2)
    preset: CameraPreset | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "SimulationCameraControlRequest":
        provided = {
            "yaw_delta_deg": self.yaw_delta_deg,
            "pitch_delta_deg": self.pitch_delta_deg,
            "distance_delta_m": self.distance_delta_m,
            "pan_right_delta_m": self.pan_right_delta_m,
            "pan_up_delta_m": self.pan_up_delta_m,
            "preset": self.preset,
        }
        allowed = {
            CameraControlAction.ORBIT: {"yaw_delta_deg", "pitch_delta_deg"},
            CameraControlAction.ZOOM: {"distance_delta_m"},
            CameraControlAction.PAN: {"pan_right_delta_m", "pan_up_delta_m"},
            CameraControlAction.PRESET: {"preset"},
        }[self.action]
        supplied = {name for name, value in provided.items() if value is not None}
        if not supplied or not supplied.issubset(allowed):
            raise ValueError(
                f"camera action {self.action.value!r} only accepts {sorted(allowed)}"
            )
        return self


class SimulationCameraState(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    preset: CameraPreset | Literal["custom"]
    yaw_deg: FiniteFloat = Field(ge=-180.0, le=180.0)
    pitch_deg: FiniteFloat = Field(ge=-85.0, le=85.0)
    distance_m: FiniteFloat = Field(ge=0.5, le=4.0)
    target_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    position_m: tuple[FiniteFloat, FiniteFloat, FiniteFloat]
    updated_at_ms: int = Field(ge=0)


class CommandExecutionStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ResetSimulationRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    seed: int | None = None


class RobotActionRequest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)


class RobotActionResult(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    operation: RobotCommandKind
    status: ToolStatus
    state: RobotState
    message: str = Field(min_length=1)
    error: ErrorResponse | None = None


class RobotCommandRecord(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    kind: RobotCommandKind
    status: CommandExecutionStatus
    submitted_at_ms: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error: ErrorResponse | None = None


class SimulationTelemetry(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    state: RobotState
    sequence: int = Field(ge=0)
    joint_positions_deg: tuple[
        FiniteFloat,
        FiniteFloat,
        FiniteFloat,
        FiniteFloat,
        FiniteFloat,
        FiniteFloat,
    ]
    trajectory_mm: list[tuple[FiniteFloat, FiniteFloat, FiniteFloat]]
    frame_sequence: int = Field(ge=0)
    updated_at_ms: int = Field(ge=0)


class SimulationHealth(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    status: Literal["healthy", "starting", "unhealthy"]
    service: Literal["robot-simulation"] = "robot-simulation"
    worker_alive: bool
    initialized: bool
    ready: bool
    queue_depth: int = Field(ge=0)
    active_command_id: str | None = Field(default=None, min_length=1, max_length=128)
    last_heartbeat_ms: int | None = Field(default=None, ge=0)
    error: str | None = None


class SimulationEvent(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    sequence: int = Field(ge=1)
    timestamp_ms: int = Field(ge=0)
    event_type: Literal[
        "worker_ready",
        "worker_failed",
        "command_queued",
        "command_started",
        "command_completed",
        "command_failed",
        "command_cancelled",
        "state_updated",
    ]
    command: RobotCommandRecord | None = None
    state: RobotState | None = None


class SimulationHeartbeat(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    type: Literal["heartbeat"] = "heartbeat"
    after_sequence: int = Field(ge=0)
    timestamp_ms: int = Field(ge=0)
