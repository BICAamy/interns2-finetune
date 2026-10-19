"""Small simulation policy projection for services that do not import SOFA/SciPy."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import yaml


DEFAULT_SIMULATION_CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "simulation.yaml"
)


@dataclass(frozen=True)
class SimulationMotionPolicyConfig:
    tcp_name: str
    entry_tolerance_mm: float
    max_relative_translation_mm: float
    move_speed_mm_s: float
    max_speed_mm_s: float
    default_relative_step_mm: float
    default_relative_rotation_deg: float
    default_rotation_joint_index: int
    joint_speed_deg_s: float
    joint_acceleration_deg_s2: float
    max_rotation_deg: float
    sequence_blend_radius_mm: float
    workspace_low_mm: tuple[float, float, float]
    workspace_high_mm: tuple[float, float, float]
    auto_execute_delay_s: float
    initial_joint_positions_deg: tuple[
        float, float, float, float, float, float
    ]


def load_simulation_motion_policy(
    path: str | Path = DEFAULT_SIMULATION_CONFIG_PATH,
) -> SimulationMotionPolicyConfig:
    """Read only the web/orchestrator values from ``simulation.yaml``."""

    selected = Path(path).expanduser().resolve(strict=True)
    data = yaml.safe_load(selected.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("entry_point_env"), dict):
        raise ValueError("simulation config must contain entry_point_env")
    section: dict[str, Any] = data["entry_point_env"]

    def positive(name: str) -> float:
        value = float(section[name])
        if not isfinite(value) or value <= 0:
            raise ValueError(f"entry_point_env.{name} must be a finite positive number")
        return value

    def joint_index(name: str) -> int:
        value = section[name]
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 6:
            raise ValueError(f"entry_point_env.{name} must be an integer from 1 to 6")
        return value

    def triple(name: str, value: Any) -> tuple[float, float, float]:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"entry_point_env.{name} must contain three numbers")
        result = tuple(float(item) for item in value)
        if any(not isfinite(item) for item in result):
            raise ValueError(f"entry_point_env.{name} must contain finite numbers")
        return result  # type: ignore[return-value]

    workspace = section.get("workspace")
    if not isinstance(workspace, dict):
        raise ValueError("entry_point_env.workspace must be a mapping")
    workspace_low_mm = triple("workspace.low_mm", workspace.get("low_mm"))
    workspace_high_mm = triple("workspace.high_mm", workspace.get("high_mm"))
    if any(low >= high for low, high in zip(workspace_low_mm, workspace_high_mm)):
        raise ValueError("simulation workspace lower bounds must be below upper bounds")
    robot = section.get("robot")
    if not isinstance(robot, dict):
        raise ValueError("entry_point_env.robot must be a mapping")
    initial_raw = robot.get("initial_joint_positions_deg")
    if not isinstance(initial_raw, (list, tuple)) or len(initial_raw) != 6:
        raise ValueError(
            "entry_point_env.robot.initial_joint_positions_deg must contain six numbers"
        )
    initial_joint_positions_deg = tuple(float(value) for value in initial_raw)
    if any(not isfinite(value) for value in initial_joint_positions_deg):
        raise ValueError("initial joint positions must be finite")

    policy = SimulationMotionPolicyConfig(
        tcp_name=str(section["tcp_name"]).strip(),
        entry_tolerance_mm=positive("reach_tolerance_mm"),
        max_relative_translation_mm=positive("maximum_relative_distance_mm"),
        move_speed_mm_s=positive("default_speed_mm_s"),
        max_speed_mm_s=positive("maximum_speed_mm_s"),
        default_relative_step_mm=positive("default_relative_step_mm"),
        default_relative_rotation_deg=positive("default_relative_rotation_deg"),
        default_rotation_joint_index=joint_index("default_rotation_joint_index"),
        joint_speed_deg_s=positive("joint_speed_deg_s"),
        joint_acceleration_deg_s2=positive("joint_acceleration_deg_s2"),
        max_rotation_deg=positive("maximum_rotation_deg"),
        sequence_blend_radius_mm=float(section["sequence_blend_radius_mm"]),
        workspace_low_mm=workspace_low_mm,
        workspace_high_mm=workspace_high_mm,
        auto_execute_delay_s=positive("auto_execute_delay_s"),
        initial_joint_positions_deg=initial_joint_positions_deg,  # type: ignore[arg-type]
    )
    if policy.move_speed_mm_s > policy.max_speed_mm_s:
        raise ValueError("simulation default speed cannot exceed its maximum speed")
    if (
        not isfinite(policy.sequence_blend_radius_mm)
        or policy.sequence_blend_radius_mm < 0
    ):
        raise ValueError("simulation sequence blend radius must be finite and nonnegative")
    if not policy.tcp_name:
        raise ValueError("entry_point_env.tcp_name cannot be empty")
    return policy
