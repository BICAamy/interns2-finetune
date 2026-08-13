"""Trace events emitted by the agent and tool adapters."""

from enum import Enum
from typing import Any

from pydantic import Field

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion


class ToolName(str, Enum):
    ROBOT_GET_STATE = "robot.get_state"
    ROBOT_MOVE_TO_ENTRY = "robot.move_to_entry"
    ROBOT_MOVE_RELATIVE = "robot.move_relative"
    ROBOT_STOP = "robot.stop"
    ROBOT_EMERGENCY_STOP = "robot.emergency_stop"
    PLANNER_PLAN_PUNCTURE = "planner.plan_puncture"


class EventPhase(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ToolEvent(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=128)
    command_id: str = Field(min_length=1, max_length=128)
    timestamp_ms: int = Field(ge=0)
    tool: ToolName
    phase: EventPhase
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
