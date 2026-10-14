"""Deterministic E05-Pro Cartesian trajectory and joint controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import dist, isfinite, sqrt
from typing import Any, Sequence

import numpy as np
from scipy.spatial.transform import Rotation

from surgical_contracts import (
    Axis,
    CoordinateSource,
    MotionState,
    MotionStepKind,
    MoveSequenceRequest,
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
    JOINT_RELATIVE = "joint_relative"
    CARTESIAN_POSE = "cartesian_pose"
    SEQUENCE = "sequence"


@dataclass(frozen=True)
class _SequenceTarget:
    """One prevalidated absolute target inside a continuous sequence."""

    kind: MotionCommandKind
    target_position_mm: tuple[float, float, float]
    target_joint_positions_rad: np.ndarray | None
    target_orientation: Rotation
    linear_speed_mm_s: float
    joint_speed_deg_s: float
    blend_radius_mm: float = 0.0


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
        self._target_joint_positions_rad: np.ndarray | None = None
        self._target_tcp_orientation: Rotation | None = None
        self._speed_mm_s = self.config.default_speed_mm_s
        self._joint_speed_deg_s = self.config.joint_speed_deg_s
        self._motion_state = MotionState.IDLE
        self._estop = False
        self._active_command_id: str | None = None
        self._last_command_id: str | None = None
        self._command_kind: MotionCommandKind | None = None
        self._active_motion_kind: MotionCommandKind | None = None
        self._sequence_targets: tuple[_SequenceTarget, ...] = ()
        self._sequence_index: int | None = None
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

    def move_joint_relative(
        self,
        joint_index: int,
        rotation_deg: float,
        speed_deg_s: float | None = None,
    ) -> str:
        self._ensure_motion_can_start()
        if type(joint_index) is not int or not 1 <= joint_index <= 6:
            raise InvalidMotionCommand("joint_index must be within 1..6")
        rotation = float(rotation_deg)
        if not isfinite(rotation) or rotation == 0.0:
            raise InvalidMotionCommand("rotation_deg must be finite and non-zero")
        if abs(rotation) > self.config.maximum_rotation_deg:
            raise InvalidMotionCommand("joint rotation exceeds maximum_rotation_deg")
        speed = self.config.joint_speed_deg_s if speed_deg_s is None else float(speed_deg_s)
        if not isfinite(speed) or speed <= 0.0:
            raise InvalidMotionCommand("speed_deg_s must be finite and positive")
        maximum = self.config.robot.joint_max_speeds_deg_s[joint_index - 1]
        if speed > maximum:
            raise InvalidMotionCommand(f"joint speed cannot exceed {maximum}")
        target = self._joint_positions_rad.copy()
        target[joint_index - 1] += np.deg2rad(rotation)
        low, high = self.config.robot.joint_limits_deg[joint_index - 1]
        target_deg = float(np.rad2deg(target[joint_index - 1]))
        if not low <= target_deg <= high:
            raise InvalidMotionCommand("joint target exceeds configured joint limit")
        snapshot = self.kinematics.forward(target)
        target_position = self._position_from_snapshot(snapshot)
        if not self.config.workspace.contains(target_position):
            raise WorkspaceViolationError("joint path target leaves the workspace")
        command_id = self._next_command_id("joint")
        self._target_joint_positions_rad = target
        self._target_position_mm = target_position
        self._joint_speed_deg_s = speed
        self._command_kind = MotionCommandKind.JOINT_RELATIVE
        self._active_motion_kind = MotionCommandKind.JOINT_RELATIVE
        self._active_command_id = command_id
        self._last_command_id = command_id
        self._motion_state = MotionState.MOVING
        return command_id

    def move_joint_absolute(
        self,
        joint_index: int,
        target_angle_deg: float,
        speed_deg_s: float | None = None,
    ) -> str:
        self._ensure_motion_can_start()
        if type(joint_index) is not int or not 1 <= joint_index <= 6:
            raise InvalidMotionCommand("joint_index must be within 1..6")
        target = float(target_angle_deg)
        if not isfinite(target):
            raise InvalidMotionCommand("target_angle_deg must be finite")
        current = float(np.rad2deg(self._joint_positions_rad[joint_index - 1]))
        delta = target - current
        if abs(delta) <= 1e-12:
            command_id = self._next_command_id("joint-absolute")
            self._last_command_id = command_id
            return command_id
        return self.move_joint_relative(joint_index, delta, speed_deg_s)

    def move_cartesian_absolute(
        self,
        target_position_mm: Sequence[float],
        speed_mm_s: float | None = None,
    ) -> str:
        target = self._vector(target_position_mm, name="target_position_mm")
        current_orientation = Rotation.from_matrix(
            self.kinematic_snapshot.tcp_transform[:3, :3]
        )
        return self._move_cartesian_pose(
            target,
            current_orientation,
            speed_mm_s=speed_mm_s,
            prefix="absolute",
        )

    def move_tcp_rotation(
        self,
        axis: Axis,
        angle_deg: float,
        *,
        absolute: bool,
        speed_mm_s: float | None = None,
    ) -> str:
        try:
            selected_axis = Axis(axis)
        except (TypeError, ValueError) as error:
            raise InvalidMotionCommand("TCP rotation axis must be x, y, or z") from error
        angle = float(angle_deg)
        if not isfinite(angle):
            raise InvalidMotionCommand("TCP rotation angle must be finite")
        current = Rotation.from_matrix(self.kinematic_snapshot.tcp_transform[:3, :3])
        rpy = current.as_euler("xyz", degrees=True)
        index = {Axis.X: 0, Axis.Y: 1, Axis.Z: 2}[selected_axis]
        delta = angle - float(rpy[index]) if absolute else angle
        if abs(delta) > self.config.maximum_rotation_deg:
            raise InvalidMotionCommand("TCP rotation exceeds maximum_rotation_deg")
        rpy[index] = angle if absolute else rpy[index] + angle
        return self._move_cartesian_pose(
            self._position_mm,
            Rotation.from_euler("xyz", rpy, degrees=True),
            speed_mm_s=speed_mm_s,
            prefix="tcp-rotation",
        )

    def _move_cartesian_pose(
        self,
        target_position_mm: Sequence[float],
        target_orientation: Rotation,
        *,
        speed_mm_s: float | None,
        prefix: str,
    ) -> str:
        self._ensure_motion_can_start()
        target = self._vector(target_position_mm, name="target_position_mm")
        if not self.config.workspace.contains(target):
            raise WorkspaceViolationError(f"target {target} mm is outside the workspace")
        self._validated_speed(speed_mm_s)
        try:
            solution = self.kinematics.inverse(
                target,
                target_orientation,
                self._joint_positions_rad,
            )
        except InverseKinematicsError as error:
            raise UnreachableTargetError(str(error)) from error
        command_id = self._next_command_id(prefix)
        self._target_joint_positions_rad = np.asarray(
            solution.joint_positions_rad,
            dtype=np.float64,
        )
        self._target_position_mm = target
        self._target_tcp_orientation = target_orientation
        self._joint_speed_deg_s = self.config.joint_speed_deg_s
        self._command_kind = MotionCommandKind.CARTESIAN_POSE
        self._active_motion_kind = MotionCommandKind.CARTESIAN_POSE
        self._active_command_id = command_id
        self._last_command_id = command_id
        self._motion_state = MotionState.MOVING
        return command_id

    def move_sequence(self, request: MoveSequenceRequest) -> str:
        """Prevalidate and execute one MotionSequence without intermediate idle states.

        Cartesian translation corners use the configured blend radius.  Joint
        and orientation targets still pass through their exact target, but the
        controller activates the following target in the same control tick so
        the externally visible state remains ``moving`` until the final step.
        """

        self._ensure_motion_can_start()
        linear_speed = self._validated_speed(request.translation_speed_mm_s)
        joint_speed = float(request.joint_speed_deg_s)
        joint_acceleration = float(request.joint_acceleration_deg_s2)
        if not isfinite(joint_speed) or joint_speed <= 0.0:
            raise InvalidMotionCommand("joint sequence speed must be finite and positive")
        if (
            not isfinite(joint_acceleration)
            or joint_acceleration <= 0.0
            or joint_acceleration > self.config.joint_acceleration_deg_s2
        ):
            raise InvalidMotionCommand(
                "joint sequence acceleration exceeds the simulation configuration"
            )

        nominal_joints = self._joint_positions_rad.copy()
        nominal_snapshot = self.kinematics.forward(nominal_joints)
        nominal_position = self._position_from_snapshot(nominal_snapshot)
        nominal_orientation = Rotation.from_matrix(
            nominal_snapshot.tcp_transform[:3, :3]
        )
        raw_targets: list[_SequenceTarget] = []
        segment_starts: list[tuple[float, float, float]] = []

        for step in request.steps:
            segment_starts.append(nominal_position)
            if step.kind in {
                MotionStepKind.CARTESIAN_RELATIVE,
                MotionStepKind.CARTESIAN_ABSOLUTE,
            }:
                if step.kind == MotionStepKind.CARTESIAN_RELATIVE:
                    assert step.translation_mm is not None
                    delta = self._vector(step.translation_mm, name="translation_mm")
                    distance_mm = sqrt(sum(component * component for component in delta))
                    if distance_mm > self.config.maximum_relative_distance_mm:
                        raise InvalidMotionCommand(
                            "sequence translation exceeds maximum_relative_distance_mm"
                        )
                    target_position = tuple(
                        current + offset
                        for current, offset in zip(nominal_position, delta)
                    )
                else:
                    assert step.target_position_mm is not None
                    target_position = self._vector(
                        step.target_position_mm,
                        name="target_position_mm",
                    )
                if not self.config.workspace.contains(target_position):
                    raise WorkspaceViolationError(
                        f"sequence target {target_position} mm is outside the workspace"
                    )
                try:
                    solution = self.kinematics.inverse(
                        target_position,
                        nominal_orientation,
                        nominal_joints,
                    )
                except InverseKinematicsError as error:
                    raise UnreachableTargetError(str(error)) from error
                nominal_joints = np.asarray(
                    solution.joint_positions_rad,
                    dtype=np.float64,
                )
                nominal_position = target_position
                raw_targets.append(_SequenceTarget(
                    kind=MotionCommandKind.RELATIVE,
                    target_position_mm=target_position,
                    target_joint_positions_rad=None,
                    target_orientation=nominal_orientation,
                    linear_speed_mm_s=linear_speed,
                    joint_speed_deg_s=joint_speed,
                ))
                continue

            if step.kind in {
                MotionStepKind.JOINT_RELATIVE,
                MotionStepKind.JOINT_ABSOLUTE,
            }:
                assert step.joint_index is not None
                joint_offset = step.joint_index - 1
                if step.kind == MotionStepKind.JOINT_RELATIVE:
                    assert step.rotation_deg is not None
                    rotation_deg = float(step.rotation_deg)
                    target_angle_deg = (
                        float(np.rad2deg(nominal_joints[joint_offset]))
                        + rotation_deg
                    )
                else:
                    assert step.target_angle_deg is not None
                    target_angle_deg = float(step.target_angle_deg)
                    rotation_deg = target_angle_deg - float(
                        np.rad2deg(nominal_joints[joint_offset])
                    )
                if abs(rotation_deg) > self.config.maximum_rotation_deg:
                    raise InvalidMotionCommand(
                        "sequence joint rotation exceeds maximum_rotation_deg"
                    )
                maximum_speed = self.config.robot.joint_max_speeds_deg_s[
                    joint_offset
                ]
                if joint_speed > maximum_speed:
                    raise InvalidMotionCommand(
                        f"joint speed cannot exceed {maximum_speed}"
                    )
                low, high = self.config.robot.joint_limits_deg[joint_offset]
                if not low <= target_angle_deg <= high:
                    raise InvalidMotionCommand(
                        "sequence joint target exceeds configured joint limit"
                    )
                nominal_joints = nominal_joints.copy()
                nominal_joints[joint_offset] = np.deg2rad(target_angle_deg)
                nominal_snapshot = self.kinematics.forward(nominal_joints)
                nominal_position = self._position_from_snapshot(nominal_snapshot)
                if not self.config.workspace.contains(nominal_position):
                    raise WorkspaceViolationError(
                        "sequence joint target leaves the workspace"
                    )
                nominal_orientation = Rotation.from_matrix(
                    nominal_snapshot.tcp_transform[:3, :3]
                )
                raw_targets.append(_SequenceTarget(
                    kind=MotionCommandKind.JOINT_RELATIVE,
                    target_position_mm=nominal_position,
                    target_joint_positions_rad=nominal_joints.copy(),
                    target_orientation=nominal_orientation,
                    linear_speed_mm_s=linear_speed,
                    joint_speed_deg_s=joint_speed,
                ))
                continue

            assert step.rotation_axis is not None
            angle = (
                step.rotation_deg
                if step.kind == MotionStepKind.TCP_ROTATION_RELATIVE
                else step.target_angle_deg
            )
            assert angle is not None
            selected_axis = Axis(step.rotation_axis)
            rpy = nominal_orientation.as_euler("xyz", degrees=True)
            axis_index = {Axis.X: 0, Axis.Y: 1, Axis.Z: 2}[selected_axis]
            delta_deg = (
                float(angle) - float(rpy[axis_index])
                if step.kind == MotionStepKind.TCP_ROTATION_ABSOLUTE
                else float(angle)
            )
            if abs(delta_deg) > self.config.maximum_rotation_deg:
                raise InvalidMotionCommand(
                    "sequence TCP rotation exceeds maximum_rotation_deg"
                )
            rpy[axis_index] += delta_deg
            nominal_orientation = Rotation.from_euler("xyz", rpy, degrees=True)
            try:
                solution = self.kinematics.inverse(
                    nominal_position,
                    nominal_orientation,
                    nominal_joints,
                )
            except InverseKinematicsError as error:
                raise UnreachableTargetError(str(error)) from error
            nominal_joints = np.asarray(
                solution.joint_positions_rad,
                dtype=np.float64,
            )
            raw_targets.append(_SequenceTarget(
                kind=MotionCommandKind.CARTESIAN_POSE,
                target_position_mm=nominal_position,
                target_joint_positions_rad=nominal_joints.copy(),
                target_orientation=nominal_orientation,
                linear_speed_mm_s=linear_speed,
                joint_speed_deg_s=self.config.joint_speed_deg_s,
            ))

        targets: list[_SequenceTarget] = []
        for index, target in enumerate(raw_targets):
            blend_radius = 0.0
            if (
                index < len(raw_targets) - 1
                and target.kind == MotionCommandKind.RELATIVE
                and raw_targets[index + 1].kind == MotionCommandKind.RELATIVE
                and self.config.sequence_blend_radius_mm > 0.0
            ):
                incoming = dist(segment_starts[index], target.target_position_mm)
                outgoing = dist(
                    target.target_position_mm,
                    raw_targets[index + 1].target_position_mm,
                )
                blend_radius = min(
                    self.config.sequence_blend_radius_mm,
                    incoming * 0.45,
                    outgoing * 0.45,
                )
            targets.append(_SequenceTarget(
                kind=target.kind,
                target_position_mm=target.target_position_mm,
                target_joint_positions_rad=target.target_joint_positions_rad,
                target_orientation=target.target_orientation,
                linear_speed_mm_s=target.linear_speed_mm_s,
                joint_speed_deg_s=target.joint_speed_deg_s,
                blend_radius_mm=blend_radius,
            ))

        if not targets:
            raise InvalidMotionCommand("motion sequence must contain at least one step")
        self._sequence_targets = tuple(targets)
        self._sequence_index = 0
        self._command_kind = MotionCommandKind.SEQUENCE
        self._active_command_id = request.command_id
        self._last_command_id = request.command_id
        self._activate_sequence_target(self._sequence_targets[0])
        self._motion_state = MotionState.MOVING
        return request.command_id

    def _activate_sequence_target(self, target: _SequenceTarget) -> None:
        self._active_motion_kind = target.kind
        self._target_position_mm = target.target_position_mm
        self._target_joint_positions_rad = (
            None
            if target.target_joint_positions_rad is None
            else target.target_joint_positions_rad.copy()
        )
        self._target_tcp_orientation = target.target_orientation
        self._speed_mm_s = target.linear_speed_mm_s
        self._joint_speed_deg_s = target.joint_speed_deg_s
        if target.kind == MotionCommandKind.RELATIVE:
            self._fixed_tcp_orientation = target.target_orientation

    def _complete_active_target(self) -> None:
        if self._command_kind == MotionCommandKind.SEQUENCE:
            assert self._sequence_index is not None
            next_index = self._sequence_index + 1
            if next_index < len(self._sequence_targets):
                self._sequence_index = next_index
                self._activate_sequence_target(self._sequence_targets[next_index])
                self._motion_state = MotionState.MOVING
                return
        self._finish_motion()

    def _active_blend_radius_mm(self) -> float:
        if (
            self._command_kind != MotionCommandKind.SEQUENCE
            or self._sequence_index is None
        ):
            return 0.0
        return self._sequence_targets[self._sequence_index].blend_radius_mm

    def _clear_sequence(self) -> None:
        self._sequence_targets = ()
        self._sequence_index = None

    def _ensure_motion_can_start(self) -> None:
        if self._estop:
            raise InvalidMotionCommand("emergency stop is active")
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
        self._target_joint_positions_rad = None
        self._target_tcp_orientation = None
        self._speed_mm_s = speed_mm_s
        self._command_kind = kind
        self._active_motion_kind = kind
        self._active_command_id = command_id
        self._last_command_id = command_id
        if dist(self._position_mm, target) <= self._completion_tolerance_mm():
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
        completed_kind = self._active_motion_kind
        top_level_kind = self._command_kind
        if completed_kind in {
            MotionCommandKind.JOINT_RELATIVE,
            MotionCommandKind.CARTESIAN_POSE,
        }:
            self._fixed_tcp_orientation = Rotation.from_matrix(
                self.kinematic_snapshot.tcp_transform[:3, :3]
            )
        self._target_joint_positions_rad = None
        self._target_tcp_orientation = None
        if top_level_kind == MotionCommandKind.ENTRY_POINT:
            self._motion_state = MotionState.AT_ENTRY
        else:
            self._motion_state = MotionState.IDLE
        self._active_command_id = None
        self._active_motion_kind = None
        self._command_kind = None
        self._clear_sequence()

    def _completion_tolerance_mm(self) -> float:
        """Use task tolerance for entry positioning and IK precision for offsets."""

        if self._active_motion_kind == MotionCommandKind.RELATIVE:
            return self.config.ik_position_tolerance_mm
        return self.config.reach_tolerance_mm

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
            if self._active_motion_kind in {
                MotionCommandKind.JOINT_RELATIVE,
                MotionCommandKind.CARTESIAN_POSE,
            }:
                if self._target_joint_positions_rad is None:
                    self.mark_failed()
                else:
                    delta = self._target_joint_positions_rad - self._joint_positions_rad
                    maximum_step = np.deg2rad(self._joint_speed_deg_s) * self.config.time_step_s
                    if np.max(np.abs(delta)) <= maximum_step:
                        candidate = self._target_joint_positions_rad.copy()
                    else:
                        candidate = self._joint_positions_rad + np.clip(
                            delta, -maximum_step, maximum_step
                        )
                    snapshot = self.kinematics.forward(candidate)
                    actual_position = self._position_from_snapshot(snapshot)
                    if not self.config.workspace.contains(actual_position):
                        self.mark_failed()
                        raise WorkspaceViolationError("joint path leaves the workspace")
                    self._joint_positions_rad = candidate
                    self._position_mm = actual_position
                    self._append_trajectory(actual_position)
                    if np.max(np.abs(delta)) <= maximum_step:
                        self._complete_active_target()
            elif self._target_position_mm is None:
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
                remaining_after_step = dist(
                    self._position_mm,
                    self._target_position_mm,
                )
                blend_radius = self._active_blend_radius_mm()
                if blend_radius > 0.0 and remaining_after_step <= blend_radius:
                    self._complete_active_target()
                elif remaining_after_step <= self._completion_tolerance_mm():
                    self._complete_active_target()
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
            reached=self._motion_state == MotionState.AT_ENTRY,
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
            estop=self._estop,
            active_command_id=self._active_command_id,
        )

    def stop(self) -> RobotState:
        self._target_position_mm = None
        self._target_joint_positions_rad = None
        self._target_tcp_orientation = None
        self._command_kind = None
        self._active_motion_kind = None
        self._clear_sequence()
        self._active_command_id = None
        self._motion_state = MotionState.ESTOP if self._estop else MotionState.STOPPED
        return self.get_state()

    def emergency_stop(self) -> RobotState:
        """Latch the simulation emergency stop and cancel active motion."""

        self._target_position_mm = None
        self._target_joint_positions_rad = None
        self._target_tcp_orientation = None
        self._command_kind = None
        self._active_motion_kind = None
        self._clear_sequence()
        self._active_command_id = None
        self._estop = True
        self._motion_state = MotionState.ESTOP
        return self.get_state()

    def mark_failed(self) -> RobotState:
        self._target_position_mm = None
        self._target_joint_positions_rad = None
        self._target_tcp_orientation = None
        self._command_kind = None
        self._active_motion_kind = None
        self._clear_sequence()
        self._active_command_id = None
        self._motion_state = MotionState.FAILED
        return self.get_state()

    @property
    def trajectory_mm(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(self._trajectory_mm)

    def clear_trajectory(self) -> int:
        """Forget the rendered path while retaining the current robot state."""

        self._trajectory_mm[:] = [self._position_mm]
        return len(self._trajectory_mm)

    @property
    def entry_point(self) -> Point3D | None:
        return self._point(self._entry_point_mm) if self._entry_point_mm is not None else None

    @property
    def joint_positions_deg(self) -> tuple[float, float, float, float, float, float]:
        return tuple(float(value) for value in np.rad2deg(self._joint_positions_rad))  # type: ignore[return-value]

    @property
    def kinematic_snapshot(self) -> KinematicSnapshot:
        return self.kinematics.forward(self._joint_positions_rad)
