"""Coordinate, unit, and relative-motion contracts."""

from __future__ import annotations

from enum import Enum
from math import sqrt

from pydantic import Field, FiniteFloat, model_validator

from .base import ContractModel


class DistanceUnit(str, Enum):
    MILLIMETER = "mm"


class CoordinateFrame(str, Enum):
    ROBOT_BASE = "robot_base"
    TOOL_CENTER_POINT = "tool_center_point"
    NEEDLE_TIP = "needle_tip"
    SIMULATION_WORLD = "simulation_world"
    SCENE_CAMERA = "scene_camera"


class CoordinateSource(str, Enum):
    USER_TEXT = "user_text"
    ASR_TEXT = "asr_text"
    STRUCTURED_DATA = "structured_data"
    IMAGE_ANNOTATION = "image_annotation"
    GESTURE = "gesture"
    CONFIGURED_DEFAULT = "configured_default"
    SIMULATION = "simulation"


class Axis(str, Enum):
    X = "x"
    Y = "y"
    Z = "z"


class Direction(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


class DistanceSource(str, Enum):
    USER_PROVIDED = "user_provided"
    CONFIGURED_DEFAULT = "configured_default"


class MotionStepKind(str, Enum):
    CARTESIAN_RELATIVE = "cartesian_relative"
    CARTESIAN_ABSOLUTE = "cartesian_absolute"
    JOINT_RELATIVE = "joint_relative"
    JOINT_ABSOLUTE = "joint_absolute"
    TCP_ROTATION_RELATIVE = "tcp_rotation_relative"
    TCP_ROTATION_ABSOLUTE = "tcp_rotation_absolute"


class Point3D(ContractModel):
    """A finite three-dimensional point in an explicit frame."""

    x: FiniteFloat
    y: FiniteFloat
    z: FiniteFloat
    unit: DistanceUnit = DistanceUnit.MILLIMETER
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    source: CoordinateSource | None = None

    def as_tuple(self) -> tuple[float, float, float]:
        return (float(self.x), float(self.y), float(self.z))

    def distance_to(self, other: "Point3D") -> float:
        if self.unit != other.unit:
            raise ValueError("Cannot compare points with different distance units")
        if self.frame != other.frame:
            raise ValueError("Cannot compare points in different coordinate frames")
        return sqrt(
            (float(self.x) - float(other.x)) ** 2
            + (float(self.y) - float(other.y)) ** 2
            + (float(self.z) - float(other.z)) ** 2
        )

    def translated(self, delta_mm: tuple[float, float, float]) -> "Point3D":
        if len(delta_mm) != 3:
            raise ValueError("delta_mm must contain exactly three values")
        return Point3D(
            x=float(self.x) + float(delta_mm[0]),
            y=float(self.y) + float(delta_mm[1]),
            z=float(self.z) + float(delta_mm[2]),
            unit=self.unit,
            frame=self.frame,
            source=CoordinateSource.SIMULATION,
        )


class RelativeMotion(ContractModel):
    """A Cartesian translation, expressed as one axis or a signed XYZ vector."""

    axis: Axis | None = None
    direction: Direction | None = None
    distance_mm: FiniteFloat | None = Field(default=None, gt=0)
    delta_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat] | None = None
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    distance_source: DistanceSource = DistanceSource.USER_PROVIDED

    @model_validator(mode="after")
    def validate_representation(self) -> "RelativeMotion":
        legacy = (self.axis, self.direction, self.distance_mm)
        if self.delta_mm is not None:
            if any(value is not None for value in legacy):
                raise ValueError("relative motion cannot mix axis and XYZ vector forms")
            if all(float(value) == 0.0 for value in self.delta_mm):
                raise ValueError("relative XYZ vector cannot be zero")
        elif any(value is None for value in legacy):
            raise ValueError("relative motion requires either a complete axis move or XYZ vector")
        return self

    def translation_mm(self) -> tuple[float, float, float]:
        if self.delta_mm is not None:
            return tuple(float(value) for value in self.delta_mm)
        assert self.axis is not None and self.direction is not None
        assert self.distance_mm is not None
        signed_distance = float(self.distance_mm)
        if self.direction == Direction.NEGATIVE:
            signed_distance = -signed_distance
        values = {Axis.X: 0.0, Axis.Y: 0.0, Axis.Z: 0.0}
        values[self.axis] = signed_distance
        return (values[Axis.X], values[Axis.Y], values[Axis.Z])


class MotionSequenceStep(ContractModel):
    """One fully typed movement in a unified ordered motion sequence."""

    kind: MotionStepKind
    translation_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat] | None = None
    target_position_mm: tuple[FiniteFloat, FiniteFloat, FiniteFloat] | None = None
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    joint_index: int | None = Field(default=None, ge=1, le=6)
    rotation_deg: FiniteFloat | None = None
    target_angle_deg: FiniteFloat | None = None
    rotation_axis: Axis | None = None
    value_source: DistanceSource = DistanceSource.USER_PROVIDED

    @model_validator(mode="after")
    def validate_step(self) -> "MotionSequenceStep":
        if self.frame != CoordinateFrame.ROBOT_BASE:
            raise ValueError("motion sequence steps currently require robot_base")
        populated = {
            "translation_mm": self.translation_mm,
            "target_position_mm": self.target_position_mm,
            "joint_index": self.joint_index,
            "rotation_deg": self.rotation_deg,
            "target_angle_deg": self.target_angle_deg,
            "rotation_axis": self.rotation_axis,
        }
        required: set[str]
        if self.kind == MotionStepKind.CARTESIAN_RELATIVE:
            required = {"translation_mm"}
            if self.translation_mm is None:
                raise ValueError("cartesian_relative requires translation_mm")
            if all(float(value) == 0.0 for value in self.translation_mm):
                raise ValueError("cartesian_relative cannot be zero")
        elif self.kind == MotionStepKind.CARTESIAN_ABSOLUTE:
            required = {"target_position_mm"}
        elif self.kind == MotionStepKind.JOINT_RELATIVE:
            required = {"joint_index", "rotation_deg"}
            if self.joint_index is None or self.rotation_deg is None:
                raise ValueError("joint_relative requires joint_index and rotation_deg")
            if float(self.rotation_deg) == 0.0:
                raise ValueError("joint_relative cannot be zero")
        elif self.kind == MotionStepKind.JOINT_ABSOLUTE:
            required = {"joint_index", "target_angle_deg"}
        elif self.kind == MotionStepKind.TCP_ROTATION_RELATIVE:
            required = {"rotation_axis", "rotation_deg"}
            if self.rotation_deg is not None and float(self.rotation_deg) == 0.0:
                raise ValueError("tcp_rotation_relative cannot be zero")
        else:
            required = {"rotation_axis", "target_angle_deg"}
        if any(value is None for name, value in populated.items() if name in required):
            raise ValueError(f"{self.kind.value} is missing required fields")
        forbidden = [
            name for name, value in populated.items()
            if name not in required and value is not None
        ]
        if forbidden:
            raise ValueError(
                f"{self.kind.value} cannot contain {', '.join(sorted(forbidden))}"
            )
        return self


class MotionSequence(ContractModel):
    """An ordered list executed one step at a time."""

    steps: tuple[MotionSequenceStep, ...] = Field(min_length=1)
