"""Versioned contracts exposed by the robot-simulation service."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field, FiniteFloat

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .errors import ErrorResponse
from .robot import RobotState, ToolStatus


class RobotCommandKind(str, Enum):
    RESET = "reset"
    MOVE_TO_ENTRY = "move_to_entry"
    MOVE_RELATIVE = "move_relative"
    STOP = "stop"
    ESTOP = "estop"


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
