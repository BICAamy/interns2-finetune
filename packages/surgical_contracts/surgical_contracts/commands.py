"""Structured commands emitted by InternS2 and validated by the runtime."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, FiniteFloat, field_validator, model_validator

from .base import SCHEMA_VERSION, ContractModel, SchemaVersion
from .coordinates import Point3D, RelativeMotion


class CommandIntent(str, Enum):
    PUNCTURE = "puncture"
    MOVE_TO_ENTRY = "move_to_entry"
    MOVE_RELATIVE = "move_relative"
    STOP = "stop"
    EMERGENCY_STOP = "emergency_stop"
    CLARIFY = "clarify"


class ParsedCommand(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    command_id: str = Field(min_length=1, max_length=128)
    intent: CommandIntent
    entry_point: Point3D | None = None
    target_point: Point3D | None = None
    relative_motion: RelativeMotion | None = None
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    confidence: FiniteFloat = Field(default=1.0, ge=0.0, le=1.0)
    summary: str = ""

    @field_validator("missing_fields")
    @classmethod
    def reject_duplicate_missing_fields(cls, value: list[str]) -> list[str]:
        if any(not field.strip() for field in value):
            raise ValueError("missing_fields cannot contain empty values")
        if len(value) != len(set(value)):
            raise ValueError("missing_fields cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_payload_for_intent(self) -> "ParsedCommand":
        if self.intent == CommandIntent.PUNCTURE:
            if self.entry_point is None:
                raise ValueError("puncture requires entry_point")
            if self.target_point is None:
                raise ValueError("puncture requires target_point")
            if self.relative_motion is not None:
                raise ValueError("puncture cannot contain relative_motion")
            if self.entry_point.frame != self.target_point.frame:
                raise ValueError("entry_point and target_point must use the same frame")
            if self.entry_point.distance_to(self.target_point) == 0:
                raise ValueError("entry_point and target_point must be different")

        elif self.intent == CommandIntent.MOVE_TO_ENTRY:
            if self.entry_point is None:
                raise ValueError("move_to_entry requires entry_point")
            if self.target_point is not None or self.relative_motion is not None:
                raise ValueError("move_to_entry only accepts entry_point")

        elif self.intent == CommandIntent.MOVE_RELATIVE:
            if self.relative_motion is None:
                raise ValueError("move_relative requires relative_motion")
            if self.entry_point is not None or self.target_point is not None:
                raise ValueError("move_relative cannot contain entry or target points")

        elif self.intent in {CommandIntent.STOP, CommandIntent.EMERGENCY_STOP}:
            if any(
                value is not None
                for value in (self.entry_point, self.target_point, self.relative_motion)
            ):
                raise ValueError(f"{self.intent.value} cannot contain a motion payload")

        elif self.intent == CommandIntent.CLARIFY:
            if self.relative_motion is not None:
                raise ValueError("clarify cannot contain an executable relative motion")
            if not self.missing_fields:
                raise ValueError("clarify requires at least one missing_fields entry")
            if not self.needs_confirmation:
                raise ValueError("clarify requires needs_confirmation=true")
            if not self.summary.strip():
                raise ValueError("clarify requires a non-empty summary")

        if self.intent != CommandIntent.CLARIFY and self.missing_fields:
            raise ValueError("executable commands cannot contain missing_fields")

        return self
