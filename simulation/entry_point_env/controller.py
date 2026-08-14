"""Deterministic E05-Pro Cartesian trajectory and joint controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import dist, isfinite, sqrt
from typing import Any, Sequence

import numpy as np
from scipy.spatial.transform import Rotation

from surgical_contracts import (
    CoordinateSource,
    MotionState,
    Point3D,
    RobotState,
    RuntimeMode,
)

from .config import EntryPointEnvConfig
from .kinematics import E05ProKinematics, InverseKinematicsError, KinematicSnapshot


class WorkspaceViolationError(ValueError):
    """Raised before motion when a target is outside coarse command bounds."""


class InvalidMotionCommand(ValueError):
    """Raised when a Cartesian motion command is malformed or unsafe."""


class UnreachableTargetError(InvalidMotionCommand):
    """Raised before motion when the E05-Pro cannot solve the requested pose."""


class MotionCommandKind(str, Enum):
    ENTRY_POINT = "entry_point"
    RELATIVE = "relative"


@dataclass(frozen=True)
class SimulationStep:
    """One externally observable simulation step."""

    sequence: int
    state: RobotState
    command_id: str | None
    target_position: Point3D | None
    position_error_mm: float | None
    reached: bool
    joint_positions_deg: tuple[float, float, float, float, float, float]
    rgb: Any | None = field(default=None, compare=False, repr=False)


class ContinuousTrajectoryController:
    """Execute straight TCP paths through valid, speed-bounded E05-Pro IK."""

    def __init__(self, config: EntryPointEnvConfig) -> None:
        self.config = config
        robot = config.robot
        tool = robot.tool_transform
        self.kinematics = E05ProKinematics(
            joint_limits_deg=robot.joint_limits_deg,
            force_flange_offset_mm=robot.force_flange_offset_mm,
            tool_translation_mm=tool.translation_mm,
            tool_rpy_deg=tool.rpy_deg,
            orientation_weight_mm_per_rad=config.ik_orientation_weight_mm_per_rad,
            position_tolerance_mm=config.ik_position_tolerance_mm,
            orientation_tolerance_deg=config.ik_orientation_tolerance_deg,
            maximum_solver_evaluations=config.ik_maximum_solver_evaluations,
        )
        self._maximum_joint_step_rad = np.deg2rad(
            np.asarray(robot.joint_max_speeds_deg_s, dtype=np.float64)
        ) * config.time_step_s
        self._command_sequence = 0
        self.reset()

    @staticmethod
    def _vector(value: Sequence[float], *, name: str) -> tuple[float, float, float]:
        if isinstance(value, (str, bytes)) or len(value) != 3:
            raise InvalidMotionCommand(f"{name} must contain exactly three values")
        result = tuple(float(component) for component in value)
        if not all(isfinite(component) for component in result):
            raise InvalidMotionCommand(f"{name} must contain finite values")
        return result  # type: ignore[return-value]

    def reset(self, seed: int | None = None) -> RobotState:
        # The MVP uses a fixed physical start configuration.  The seed remains
        # part of the API for deterministic future scene randomization.
        self._seed = seed
        self._joint_positions_rad = np.deg2rad(
            np.asarray(self.config.robot.initial_joint_positions_deg, dtype=np.float64)
        )
        initial_snapshot = self.kinematics.forward(self._joint_positions_rad)
        self._fixed_tcp_orientation = Rotation.from_matrix(
            initial_snapshot.tcp_transform[:3, :3]
        )
        self._position_mm = self._position_from_snapshot(initial_snapshot)
        if not self.config.workspace.contains(self._position_mm):
            raise ValueError("initial E05-Pro TCP pose must be inside the configured workspace")

        self._entry_point_mm: tuple[float, float, float] | None = None
        self._target_position_mm: tuple[float, float, float] | None = None
        self._speed_mm_s = self.config.default_speed_mm_s
        self._motion_state = MotionState.IDLE
        self._active_command_id: str | None = None
        self._last_command_id: str | None = None
        self._command_kind: MotionCommandKind | None = None
        self._step_sequence = 0
        self._command_sequence = 0
        self._trajectory_mm: list[tuple[float, float, float]] = [self._position_mm]
        return self.get_state()

    @staticmethod
    def _position_from_snapshot(
        snapshot: KinematicSnapshot,
    ) -> tuple[float, float, float]:
        return tuple(float(value) for value in snapshot.tcp_transform[:3, 3])  # type: ignore[return-value]

    def _point(self, position_mm: Sequence[float]) -> Point3D:
        position = self._vector(position_mm, name="position_mm")
        return Point3D(
            x=position[0],
            y=position[1],
            z=position[2],
            frame=self.config.coordinate_frame,
            source=CoordinateSource.SIMULATION,
        )

    def _validate_point(self, point: Point3D) -> tuple[float, float, float]:
        if point.frame != self.config.coordinate_frame:
            raise InvalidMotionCommand(
                f"expected coordinate frame {self.config.coordinate_frame.value}, "
                f"received {point.frame.value}"
            )
        position = self._vector(point.as_tuple(), name="point")
        if not self.config.workspace.contains(position):
            raise WorkspaceViolationError(f"target {position} mm is outside the workspace")
        return position

    def _validate_reachable(self, target: Sequence[float]) -> None:
        try:
            self.kinematics.inverse(
                target,
                self._fixed_tcp_orientation,
                self._joint_positions_rad,
            )
        except InverseKinematicsError as error:
            raise UnreachableTargetError(str(error)) from error

    def _validated_speed(self, speed_mm_s: float | None) -> float:
        speed = self.config.default_speed_mm_s if speed_mm_s is None else float(speed_mm_s)
        if not isfinite(speed) or speed <= 0.0:
            raise InvalidMotionCommand("speed_mm_s must be a finite positive number")
        if speed > self.config.maximum_speed_mm_s:
            raise InvalidMotionCommand(
                f"speed_mm_s cannot exceed {self.config.maximum_speed_mm_s}"
            )
        return speed

    def _next_command_id(self, prefix: str) -> str:
        self._command_sequence += 1
        return f"{prefix}-{self._command_sequence:06d}"

    def set_entry_point(self, point: Point3D) -> None:
        self._ensure_motion_can_start()
        target = self._validate_point(point)
        self._validate_reachable(target)
        self._entry_point_mm = target

    def move_to_entry(self, point: Point3D, speed_mm_s: float | None = None) -> str:
        self._ensure_motion_can_start()
        target = self._validate_point(point)
        self._validate_reachable(target)
        speed = self._validated_speed(speed_mm_s)
        self._entry_point_mm = target
        return self._start_motion(target, speed, MotionCommandKind.ENTRY_POINT, "entry")

    def move_relative(
        self,
        delta_mm: Sequence[float],
        speed_mm_s: float | None = None,
    ) -> str:
        self._ensure_motion_can_start()
        delta = self._vector(delta_mm, name="delta_mm")
        distance_mm = sqrt(sum(component * component for component in delta))
        if distance_mm == 0.0:
            raise InvalidMotionCommand("delta_mm cannot be the zero vector")
        if distance_mm > self.config.maximum_relative_distance_mm:
            raise InvalidMotionCommand(
                "relative movement exceeds maximum_relative_distance_mm"
            )
        target = tuple(
            current + offset for current, offset in zip(self._position_mm, delta)
        )
        if not self.config.workspace.contains(target):
            raise WorkspaceViolationError(f"relative target {target} mm is outside the workspace")
        self._validate_reachable(target)
        speed = self._validated_speed(speed_mm_s)
        return self._start_motion(target, speed, MotionCommandKind.RELATIVE, "relative")

    def _ensure_motion_can_start(self) -> None:
        if self._motion_state == MotionState.MOVING:
            raise InvalidMotionCommand("cannot replace a motion command while it is moving")

    def _start_motion(
        self,
        target: tuple[float, float, float],
        speed_mm_s: float,
        kind: MotionCommandKind,
        prefix: str,
    ) -> str:
        command_id = self._next_command_id(prefix)
        self._target_position_mm = target
        self._speed_mm_s = speed_mm_s
        self._command_kind = kind
        self._active_command_id = command_id
        self._last_command_id = command_id
        if dist(self._position_mm, target) <= self.config.reach_tolerance_mm:
            self._finish_motion()
        else:
            self._motion_state = MotionState.MOVING
        return command_id

    def _append_trajectory(self, position: tuple[float, float, float]) -> None:
        if self._trajectory_mm[-1] != position:
            self._trajectory_mm.append(position)
        overflow = len(self._trajectory_mm) - self.config.trajectory_history_limit
        if overflow > 0:
            del self._trajectory_mm[:overflow]

    def _finish_motion(self) -> None:
        if self._command_kind == MotionCommandKind.ENTRY_POINT:
            self._motion_state = MotionState.AT_ENTRY
        else:
            self._motion_state = MotionState.IDLE
        self._active_command_id = None

    def _solve_speed_bounded_waypoint(
        self,
        desired_position_mm: np.ndarray,
    ) -> tuple[np.ndarray, tuple[float, float, float]]:
        current_position = np.asarray(self._position_mm, dtype=np.float64)
        requested_delta = desired_position_mm - current_position
        scale = 1.0

        for _ in range(10):
            candidate_position = current_position + requested_delta * scale
            solution = self.kinematics.inverse(
                candidate_position,
                self._fixed_tcp_orientation,
                self._joint_positions_rad,
            )
            candidate_joints = np.asarray(solution.joint_positions_rad, dtype=np.float64)
            joint_delta = np.abs(candidate_joints - self._joint_positions_rad)
            if np.all(joint_delta <= self._maximum_joint_step_rad + 1e-10):
                snapshot = self.kinematics.forward(candidate_joints)
                return candidate_joints, self._position_from_snapshot(snapshot)

            nonzero = joint_delta > 1e-12
            speed_ratio = float(
                np.min(self._maximum_joint_step_rad[nonzero] / joint_delta[nonzero])
            )
            scale *= max(0.05, min(0.95, speed_ratio * 0.95))

        raise RuntimeError("no Cartesian substep satisfies the E05-Pro joint speed limits")

    def step(self) -> SimulationStep:
        self._step_sequence += 1
        if self._motion_state == MotionState.MOVING:
            if self._target_position_mm is None:
                self.mark_failed()
            else:
                remaining = dist(self._position_mm, self._target_position_mm)
                maximum_step_mm = self._speed_mm_s * self.config.time_step_s
                if remaining <= maximum_step_mm:
                    desired_position = np.asarray(self._target_position_mm, dtype=np.float64)
                else:
                    ratio = maximum_step_mm / remaining
                    desired_position = np.asarray(self._position_mm, dtype=np.float64) + (
                        np.asarray(self._target_position_mm, dtype=np.float64)
                        - np.asarray(self._position_mm, dtype=np.float64)
                    ) * ratio

                try:
                    joints, actual_position = self._solve_speed_bounded_waypoint(
                        desired_position
                    )
                except (InverseKinematicsError, RuntimeError):
                    self.mark_failed()
                    raise
                self._joint_positions_rad = joints
                self._position_mm = actual_position
                self._append_trajectory(actual_position)
                if dist(self._position_mm, self._target_position_mm) <= self.config.reach_tolerance_mm:
                    self._finish_motion()
        return self.snapshot()

    def snapshot(self) -> SimulationStep:
        error = None
        if self._target_position_mm is not None:
            error = dist(self._position_mm, self._target_position_mm)
        return SimulationStep(
            sequence=self._step_sequence,
            state=self.get_state(),
            command_id=self._active_command_id or self._last_command_id,
            target_position=(
                self._point(self._target_position_mm)
                if self._target_position_mm is not None
                else None
            ),
            position_error_mm=error,
            reached=(
                self._command_kind == MotionCommandKind.ENTRY_POINT
                and self._motion_state == MotionState.AT_ENTRY
            ),
            joint_positions_deg=self.joint_positions_deg,
        )

    def get_state(self) -> RobotState:
        orientation = Rotation.from_matrix(
            self.kinematic_snapshot.tcp_transform[:3, :3]
        ).as_quat()
        return RobotState(
            mode=RuntimeMode.SIMULATION,
            tcp=self.config.tcp_name,
            tcp_position=self._point(self._position_mm),
            orientation_xyzw=tuple(float(value) for value in orientation),
            motion_state=self._motion_state,
            estop=False,
            active_command_id=self._active_command_id,
        )

    def stop(self) -> RobotState:
        self._target_position_mm = None
        self._command_kind = None
        self._active_command_id = None
        self._motion_state = MotionState.STOPPED
        return self.get_state()

    def mark_failed(self) -> RobotState:
        self._active_command_id = None
        self._motion_state = MotionState.FAILED
        return self.get_state()

    @property
    def trajectory_mm(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(self._trajectory_mm)

    @property
    def entry_point(self) -> Point3D | None:
        return self._point(self._entry_point_mm) if self._entry_point_mm is not None else None

    @property
    def joint_positions_deg(self) -> tuple[float, float, float, float, float, float]:
        return tuple(float(value) for value in np.rad2deg(self._joint_positions_rad))  # type: ignore[return-value]

    @property
    def kinematic_snapshot(self) -> KinematicSnapshot:
        return self.kinematics.forward(self._joint_positions_rad)
