"""Coordinate, unit, and relative-motion contracts."""

from __future__ import annotations

from enum import Enum
from math import sqrt

from pydantic import Field, FiniteFloat

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
    """A positive distance along one signed Cartesian axis."""

    axis: Axis
    direction: Direction
    distance_mm: FiniteFloat = Field(gt=0)
    frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    distance_source: DistanceSource = DistanceSource.USER_PROVIDED

    def translation_mm(self) -> tuple[float, float, float]:
        signed_distance = float(self.distance_mm)
        if self.direction == Direction.NEGATIVE:
            signed_distance = -signed_distance
        values = {Axis.X: 0.0, Axis.Y: 0.0, Axis.Z: 0.0}
        values[self.axis] = signed_distance
        return (values[Axis.X], values[Axis.Y], values[Axis.Z])
