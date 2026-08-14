"""E05-Pro force-control kinematics derived from the vendor E05 model.

All public translations in this module are millimetres.  Joint angles are
radians internally and degrees at configuration/telemetry boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import pi
from typing import Sequence

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


class InverseKinematicsError(ValueError):
    """Raised when a Cartesian pose has no acceptable E05-Pro joint solution."""


@dataclass(frozen=True)
class IKResult:
    joint_positions_rad: tuple[float, float, float, float, float, float]
    position_error_mm: float
    orientation_error_rad: float


@dataclass(frozen=True)
class KinematicSnapshot:
    """World transforms for the six links, force flange, and configured TCP."""

    link_transforms: tuple[np.ndarray, ...]
    flange_transform: np.ndarray
    tcp_transform: np.ndarray


def _transform(
    translation_mm: Sequence[float] = (0.0, 0.0, 0.0),
    rpy_rad: Sequence[float] = (0.0, 0.0, 0.0),
) -> np.ndarray:
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = Rotation.from_euler("xyz", rpy_rad).as_matrix()
    transform[:3, 3] = np.asarray(translation_mm, dtype=np.float64)
    return transform


def _rotation_about_z(angle_rad: float) -> np.ndarray:
    return _transform(rpy_rad=(0.0, 0.0, angle_rad))


class E05ProKinematics:
    """Forward/inverse kinematics for the six-axis E05-Pro force variant.

    The six joint origins and axes come from Huayan's ``485/elfin5`` xacro at
    commit ``84baf18``.  The standard E05 xacro's 146 mm terminal dimension is
    replaced with the E05-Pro force-control drawing's measured 184 mm
    J6-to-flange dimension.
    """

    SOURCE_REPOSITORY = "https://github.com/huayan-robotics/elfin_model"
    SOURCE_COMMIT = "84baf18d37eefa46b6f092c7fa1f105f81f70ecb"
    SOURCE_VARIANT = "485/elfin5"

    # (translation in mm, fixed RPY in radians) from parent link to joint.
    JOINT_ORIGINS = (
        ((0.0, 0.0, 220.0), (0.0, 0.0, 0.0)),
        ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, 0.0)),
        ((0.0, 380.0, 0.0), (-pi, 0.0, pi / 2.0)),
        ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, pi / 2.0)),
        ((0.0, 0.0, 420.0), (-pi / 2.0, 0.0, 0.0)),
        ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, 0.0)),
    )

    def __init__(
        self,
        *,
        joint_limits_deg: Sequence[Sequence[float]],
        force_flange_offset_mm: float,
        tool_translation_mm: Sequence[float],
        tool_rpy_deg: Sequence[float],
        orientation_weight_mm_per_rad: float = 100.0,
        position_tolerance_mm: float = 0.05,
        orientation_tolerance_deg: float = 0.05,
        maximum_solver_evaluations: int = 300,
    ) -> None:
        limits = np.asarray(joint_limits_deg, dtype=np.float64)
        if limits.shape != (6, 2):
            raise ValueError("joint_limits_deg must have shape 6x2")
        if not np.all(np.isfinite(limits)) or np.any(limits[:, 0] >= limits[:, 1]):
            raise ValueError("joint limits must be finite ordered pairs")
        if force_flange_offset_mm <= 0.0:
            raise ValueError("force_flange_offset_mm must be positive")
        if orientation_weight_mm_per_rad <= 0.0:
            raise ValueError("orientation_weight_mm_per_rad must be positive")
        if position_tolerance_mm <= 0.0 or orientation_tolerance_deg <= 0.0:
            raise ValueError("IK tolerances must be positive")
        if maximum_solver_evaluations <= 0:
            raise ValueError("maximum_solver_evaluations must be positive")

        tool_translation = np.asarray(tool_translation_mm, dtype=np.float64)
        tool_rpy = np.asarray(tool_rpy_deg, dtype=np.float64)
        if tool_translation.shape != (3,) or tool_rpy.shape != (3,):
            raise ValueError("tool translation and orientation must contain three values")
        if not np.all(np.isfinite(tool_translation)) or not np.all(np.isfinite(tool_rpy)):
            raise ValueError("tool transform must be finite")

        self.joint_limits_rad = np.deg2rad(limits)
        self.force_flange_offset_mm = float(force_flange_offset_mm)
        self.tool_transform_from_flange = _transform(
            tool_translation,
            np.deg2rad(tool_rpy),
        )
        self.orientation_weight_mm_per_rad = float(orientation_weight_mm_per_rad)
        self.position_tolerance_mm = float(position_tolerance_mm)
        self.orientation_tolerance_rad = float(np.deg2rad(orientation_tolerance_deg))
        self.maximum_solver_evaluations = int(maximum_solver_evaluations)

    @staticmethod
    def _joints(joint_positions_rad: Sequence[float]) -> np.ndarray:
        joints = np.asarray(joint_positions_rad, dtype=np.float64)
        if joints.shape != (6,) or not np.all(np.isfinite(joints)):
            raise ValueError("joint positions must contain six finite values")
        return joints

    def within_joint_limits(self, joint_positions_rad: Sequence[float]) -> bool:
        joints = self._joints(joint_positions_rad)
        return bool(
            np.all(joints >= self.joint_limits_rad[:, 0] - 1e-12)
            and np.all(joints <= self.joint_limits_rad[:, 1] + 1e-12)
        )

    def forward(self, joint_positions_rad: Sequence[float]) -> KinematicSnapshot:
        joints = self._joints(joint_positions_rad)
        if not self.within_joint_limits(joints):
            raise ValueError("joint positions exceed the configured E05-Pro limits")

        world_from_link = np.eye(4, dtype=np.float64)
        links: list[np.ndarray] = []
        for (translation_mm, rpy_rad), joint_angle in zip(self.JOINT_ORIGINS, joints):
            world_from_link = (
                world_from_link
                @ _transform(translation_mm, rpy_rad)
                @ _rotation_about_z(float(joint_angle))
            )
            links.append(world_from_link.copy())

        world_from_flange = world_from_link @ _transform(
            (0.0, 0.0, self.force_flange_offset_mm)
        )
        world_from_tcp = world_from_flange @ self.tool_transform_from_flange
        return KinematicSnapshot(
            link_transforms=tuple(links),
            flange_transform=world_from_flange,
            tcp_transform=world_from_tcp,
        )

    def inverse(
        self,
        target_position_mm: Sequence[float],
        target_orientation: Rotation,
        seed_joint_positions_rad: Sequence[float],
    ) -> IKResult:
        target_position = np.asarray(target_position_mm, dtype=np.float64)
        if target_position.shape != (3,) or not np.all(np.isfinite(target_position)):
            raise ValueError("target_position_mm must contain three finite values")
        seed = self._joints(seed_joint_positions_rad)
        if not self.within_joint_limits(seed):
            raise ValueError("IK seed exceeds the configured E05-Pro limits")

        def residual(joints: np.ndarray) -> np.ndarray:
            tcp = self.forward(joints).tcp_transform
            position_error = tcp[:3, 3] - target_position
            orientation_error = (
                target_orientation.inv() * Rotation.from_matrix(tcp[:3, :3])
            ).as_rotvec()
            return np.concatenate(
                (
                    position_error,
                    orientation_error * self.orientation_weight_mm_per_rad,
                )
            )

        result = least_squares(
            residual,
            seed,
            bounds=(self.joint_limits_rad[:, 0], self.joint_limits_rad[:, 1]),
            max_nfev=self.maximum_solver_evaluations,
            xtol=1e-11,
            ftol=1e-11,
            gtol=1e-11,
        )
        solved = self.forward(result.x).tcp_transform
        position_error_mm = float(np.linalg.norm(solved[:3, 3] - target_position))
        orientation_error_rad = float(
            np.linalg.norm(
                (
                    target_orientation.inv()
                    * Rotation.from_matrix(solved[:3, :3])
                ).as_rotvec()
            )
        )
        if (
            not result.success
            or position_error_mm > self.position_tolerance_mm
            or orientation_error_rad > self.orientation_tolerance_rad
        ):
            raise InverseKinematicsError(
                "target has no acceptable E05-Pro IK solution "
                f"(position_error_mm={position_error_mm:.6f}, "
                f"orientation_error_deg={np.rad2deg(orientation_error_rad):.6f})"
            )

        return IKResult(
            joint_positions_rad=tuple(float(value) for value in result.x),  # type: ignore[arg-type]
            position_error_mm=position_error_mm,
            orientation_error_rad=orientation_error_rad,
        )

