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
    )
    if policy.move_speed_mm_s > policy.max_speed_mm_s:
        raise ValueError("simulation default speed cannot exceed its maximum speed")
    if not policy.tcp_name:
        raise ValueError("entry_point_env.tcp_name cannot be empty")
    return policy
