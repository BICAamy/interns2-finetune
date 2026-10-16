"""Step 14 gesture-recognition and arbitration HTTP models."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GestureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GestureName(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    FORWARD = "forward"
    BACKWARD = "backward"
    STOP = "stop"
    ESTOP = "estop"
    NONE = "none"
    UNCERTAIN = "uncertain"


class GestureFrameRequest(GestureModel):
    """One raw, unmirrored browser-camera frame."""

    image_data_url: str = Field(min_length=32, max_length=3_000_000)
    captured_at_ms: int = Field(ge=0)

    @field_validator("image_data_url")
    @classmethod
    def validate_image_data_url(cls, value: str) -> str:
        prefixes = (
            "data:image/jpeg;base64,",
            "data:image/png;base64,",
            "data:image/webp;base64,",
        )
        if not value.startswith(prefixes):
            raise ValueError("gesture frame must be a JPEG, PNG, or WebP data URL")
        return value


class GestureRecognition(GestureModel):
    gesture: GestureName
    confidence: float = Field(ge=0.0, le=1.0)
    hand_detected: bool
    model: str
    latency_ms: int = Field(ge=0)
    tool_call_id: str | None = None


class GestureDecision(str, Enum):
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    SUPPRESSED_VOICE = "suppressed_voice"
    SUPPRESSED_BUSY = "suppressed_busy"
    SUPPRESSED_LATCHED = "suppressed_latched"
    SUPPRESSED_COOLDOWN = "suppressed_cooldown"
    SAFETY_STOP = "safety_stop"
    SAFETY_ESTOP = "safety_estop"


class GestureFrameResponse(GestureModel):
    schema_version: Literal["1.0"] = "1.0"
    recognition: GestureRecognition
    decision: GestureDecision
    message: str
    mapped_command: dict[str, Any] | None = None
    session_snapshot: dict[str, Any] | None = None


class VoiceActivityRequest(GestureModel):
    active: bool


class VoiceActivityResponse(GestureModel):
    schema_version: Literal["1.0"] = "1.0"
    active: bool
    observed_at_ms: int = Field(ge=0)


class GestureResetResponse(GestureModel):
    schema_version: Literal["1.0"] = "1.0"
    reset: Literal[True] = True
