"""Validated configuration for the E05-Pro entry-point environment."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from surgical_contracts import CoordinateFrame


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "simulation.yaml"


def _values(
    name: str,
    value: Sequence[Any],
    *,
    length: int,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or len(value) != length:
        raise ValueError(f"{name} must contain exactly {length} values")
    result = tuple(float(component) for component in value)
    if not all(isfinite(component) for component in result):
        raise ValueError(f"{name} must contain only finite values")
    return result


def _triple(name: str, value: Sequence[Any]) -> tuple[float, float, float]:
    return _values(name, value, length=3)  # type: ignore[return-value]


def _six(name: str, value: Sequence[Any]) -> tuple[float, float, float, float, float, float]:
    return _values(name, value, length=6)  # type: ignore[return-value]


@dataclass(frozen=True)
class WorkspaceBounds:
    """Coarse Cartesian command bounds in the robot-base frame, in mm.

    Passing this box is necessary but not sufficient: every target is also
    checked by the E05-Pro inverse kinematics before motion starts.
    """

    low_mm: tuple[float, float, float]
    high_mm: tuple[float, float, float]

    def __post_init__(self) -> None:
        low = _triple("workspace.low_mm", self.low_mm)
        high = _triple("workspace.high_mm", self.high_mm)
        if any(lower >= upper for lower, upper in zip(low, high)):
            raise ValueError("each workspace lower bound must be below its upper bound")
        object.__setattr__(self, "low_mm", low)
        object.__setattr__(self, "high_mm", high)

    def contains(self, point_mm: Sequence[float]) -> bool:
        point = _triple("point_mm", point_mm)
        return all(
            lower <= component <= upper
            for component, lower, upper in zip(point, self.low_mm, self.high_mm)
        )


@dataclass(frozen=True)
class ToolTransformConfig:
    """Rigid transform from the E05-Pro force flange to the needle TCP."""

    translation_mm: tuple[float, float, float]
    rpy_deg: tuple[float, float, float]
    provisional: bool
    real_robot_motion_allowed: bool
    note: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "translation_mm",
            _triple("tool_transform.translation_mm", self.translation_mm),
        )
        object.__setattr__(self, "rpy_deg", _triple("tool_transform.rpy_deg", self.rpy_deg))
        if self.provisional and self.real_robot_motion_allowed:
            raise ValueError("a provisional tool transform cannot allow real robot motion")
        if not self.note.strip():
            raise ValueError("tool_transform.note cannot be empty")


@dataclass(frozen=True)
class E05ProRobotConfig:
    """Vendor model identity, force-terminal geometry, and joint constraints."""

    model_name: str
    source_repository: str
    source_commit: str
    source_variant: str
    force_control_variant: bool
    force_flange_offset_mm: float
    joint_limits_deg: tuple[tuple[float, float], ...]
    joint_max_speeds_deg_s: tuple[float, float, float, float, float, float]
    initial_joint_positions_deg: tuple[float, float, float, float, float, float]
    tool_transform: ToolTransformConfig

    def __post_init__(self) -> None:
        if self.model_name != "E05-Pro":
            raise ValueError("Step 5 is fixed to the purchased E05-Pro model")
        if not self.force_control_variant:
            raise ValueError("the purchased E05-Pro must use the force-control variant")
        if not self.source_repository.startswith("https://github.com/huayan-robotics/"):
            raise ValueError("robot model source must be an official Huayan repository")
        if len(self.source_commit) != 40:
            raise ValueError("source_commit must be a full 40-character commit SHA")
        if self.source_variant != "485/elfin5":
            raise ValueError("the verified E05-Pro base kinematics use 485/elfin5")
        flange_offset = float(self.force_flange_offset_mm)
        if not isfinite(flange_offset) or flange_offset <= 0.0:
            raise ValueError("force_flange_offset_mm must be positive")
        object.__setattr__(self, "force_flange_offset_mm", flange_offset)

        limits = tuple(
            _values(f"joint_limits_deg[{index}]", pair, length=2)
            for index, pair in enumerate(self.joint_limits_deg)
        )
        if len(limits) != 6 or any(lower >= upper for lower, upper in limits):
            raise ValueError("joint_limits_deg must contain six ordered pairs")
        object.__setattr__(self, "joint_limits_deg", limits)

        speeds = _six("joint_max_speeds_deg_s", self.joint_max_speeds_deg_s)
        if any(speed <= 0.0 for speed in speeds):
            raise ValueError("joint maximum speeds must be positive")
        object.__setattr__(self, "joint_max_speeds_deg_s", speeds)

        initial = _six("initial_joint_positions_deg", self.initial_joint_positions_deg)
        if any(
            position < lower or position > upper
            for position, (lower, upper) in zip(initial, limits)
        ):
            raise ValueError("initial joint positions exceed the E05-Pro limits")
        object.__setattr__(self, "initial_joint_positions_deg", initial)


@dataclass(frozen=True)
class EntryPointEnvConfig:
    """Runtime settings with public Cartesian distances expressed in mm."""

    workspace: WorkspaceBounds
    robot: E05ProRobotConfig
    time_step_s: float = 0.05
    default_speed_mm_s: float = 20.0
    maximum_speed_mm_s: float = 50.0
    reach_tolerance_mm: float = 0.5
    maximum_relative_distance_mm: float = 50.0
    image_shape: tuple[int, int] = (600, 600)
    trajectory_history_limit: int = 2048
    tcp_name: str = "needle_tip"
    coordinate_frame: CoordinateFrame = CoordinateFrame.ROBOT_BASE
    ik_orientation_weight_mm_per_rad: float = 100.0
    ik_position_tolerance_mm: float = 0.05
    ik_orientation_tolerance_deg: float = 0.05
    ik_maximum_solver_evaluations: int = 300

    def __post_init__(self) -> None:
        for name in (
            "time_step_s",
            "default_speed_mm_s",
            "maximum_speed_mm_s",
            "reach_tolerance_mm",
            "maximum_relative_distance_mm",
            "ik_orientation_weight_mm_per_rad",
            "ik_position_tolerance_mm",
            "ik_orientation_tolerance_deg",
        ):
            value = float(getattr(self, name))
            if not isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be a finite positive number")
            object.__setattr__(self, name, value)
        if self.default_speed_mm_s > self.maximum_speed_mm_s:
            raise ValueError("default_speed_mm_s cannot exceed maximum_speed_mm_s")
        if len(self.image_shape) != 2 or any(int(size) <= 0 for size in self.image_shape):
            raise ValueError("image_shape must contain two positive integers")
        object.__setattr__(self, "image_shape", tuple(int(size) for size in self.image_shape))
        if self.trajectory_history_limit < 2:
            raise ValueError("trajectory_history_limit must be at least 2")
        if self.ik_maximum_solver_evaluations <= 0:
            raise ValueError("ik_maximum_solver_evaluations must be positive")
        if not self.tcp_name.strip():
            raise ValueError("tcp_name cannot be empty")

    @property
    def real_robot_ready(self) -> bool:
        tool = self.robot.tool_transform
        return not tool.provisional and tool.real_robot_motion_allowed

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "EntryPointEnvConfig":
        section = data.get("entry_point_env", data)
        if not isinstance(section, Mapping):
            raise ValueError("entry_point_env configuration must be a mapping")
        workspace_data = section.get("workspace")
        robot_data = section.get("robot")
        image_data = section.get("image", {})
        ik_data = section.get("inverse_kinematics", {})
        if not isinstance(workspace_data, Mapping):
            raise ValueError("entry_point_env.workspace must be a mapping")
        if not isinstance(robot_data, Mapping):
            raise ValueError("entry_point_env.robot must be a mapping")
        if not isinstance(image_data, Mapping) or not isinstance(ik_data, Mapping):
            raise ValueError("image and inverse_kinematics settings must be mappings")
        tool_data = robot_data.get("tool_transform")
        if not isinstance(tool_data, Mapping):
            raise ValueError("entry_point_env.robot.tool_transform must be a mapping")

        robot = E05ProRobotConfig(
            model_name=str(robot_data["model_name"]),
            source_repository=str(robot_data["source_repository"]),
            source_commit=str(robot_data["source_commit"]),
            source_variant=str(robot_data["source_variant"]),
            force_control_variant=bool(robot_data["force_control_variant"]),
            force_flange_offset_mm=float(robot_data["force_flange_offset_mm"]),
            joint_limits_deg=tuple(
                tuple(float(component) for component in pair)
                for pair in robot_data["joint_limits_deg"]
            ),
            joint_max_speeds_deg_s=_six(
                "joint_max_speeds_deg_s",
                robot_data["joint_max_speeds_deg_s"],
            ),
            initial_joint_positions_deg=_six(
                "initial_joint_positions_deg",
                robot_data["initial_joint_positions_deg"],
            ),
            tool_transform=ToolTransformConfig(
                translation_mm=_triple(
                    "tool_transform.translation_mm",
                    tool_data["translation_mm"],
                ),
                rpy_deg=_triple("tool_transform.rpy_deg", tool_data["rpy_deg"]),
                provisional=bool(tool_data["provisional"]),
                real_robot_motion_allowed=bool(tool_data["real_robot_motion_allowed"]),
                note=str(tool_data["note"]),
            ),
        )

        return cls(
            workspace=WorkspaceBounds(
                low_mm=_triple("workspace.low_mm", workspace_data["low_mm"]),
                high_mm=_triple("workspace.high_mm", workspace_data["high_mm"]),
            ),
            robot=robot,
            time_step_s=float(section.get("time_step_s", 0.05)),
            default_speed_mm_s=float(section.get("default_speed_mm_s", 20.0)),
            maximum_speed_mm_s=float(section.get("maximum_speed_mm_s", 50.0)),
            reach_tolerance_mm=float(section.get("reach_tolerance_mm", 0.5)),
            maximum_relative_distance_mm=float(
                section.get("maximum_relative_distance_mm", 50.0)
            ),
            image_shape=(
                int(image_data.get("height", 600)),
                int(image_data.get("width", 600)),
            ),
            trajectory_history_limit=int(section.get("trajectory_history_limit", 2048)),
            tcp_name=str(section.get("tcp_name", "needle_tip")),
            coordinate_frame=CoordinateFrame(
                section.get("coordinate_frame", CoordinateFrame.ROBOT_BASE.value)
            ),
            ik_orientation_weight_mm_per_rad=float(
                ik_data.get("orientation_weight_mm_per_rad", 100.0)
            ),
            ik_position_tolerance_mm=float(ik_data.get("position_tolerance_mm", 0.05)),
            ik_orientation_tolerance_deg=float(
                ik_data.get("orientation_tolerance_deg", 0.05)
            ),
            ik_maximum_solver_evaluations=int(
                ik_data.get("maximum_solver_evaluations", 300)
            ),
        )

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "EntryPointEnvConfig":
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        if not isinstance(data, Mapping):
            raise ValueError(f"configuration file must contain a mapping: {config_path}")
        return cls.from_mapping(data)

