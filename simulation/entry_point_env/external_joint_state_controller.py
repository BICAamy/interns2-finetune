"""Passive E05-Pro FK from authenticated *actual* joint feedback.

This controller deliberately has no IK, target, or motion methods. Until the
Step 8 calibration is complete, identity joint mapping and Base-to-SOFA are
only an explicitly uncalibrated visual preview.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np

from surgical_contracts import RobotProvider, RobotTelemetry, RuntimeMode, SourceFreshness

from edge_gateway.transforms import matrix_from_translation_quaternion, transform_point

from .config import EntryPointEnvConfig
from .kinematics import E05ProKinematics, KinematicSnapshot, transform_snapshot


@dataclass(frozen=True)
class ExternalJointSnapshot:
    source_sequence: int
    gateway_session_id: str
    actual_joint_positions_deg: tuple[float, float, float, float, float, float]
    visual_joint_positions_rad: tuple[float, float, float, float, float, float]
    kinematics_robot_base: KinematicSnapshot
    kinematics: KinematicSnapshot
    actual_tcp_robot_base_mm: tuple[float, float, float]
    actual_tcp_sofa_world_mm: tuple[float, float, float] | None


class ExternalJointStateController:
    """Accept fresh monotonic samples; retain the last pose on any bad input."""

    def __init__(
        self,
        config: EntryPointEnvConfig,
        *,
        stale_ms: int,
        sign: Sequence[int] | None = None,
        zero_offset_deg: Sequence[float] | None = None,
        base_to_sofa_translation_mm: Sequence[float] | None = None,
        base_to_sofa_quaternion_xyzw: Sequence[float] | None = None,
    ) -> None:
        if stale_ms <= 0:
            raise ValueError("stale_ms must be positive")
        if (sign is None) != (zero_offset_deg is None):
            raise ValueError("joint sign and zero offset must be provided together")
        self.sign = self._validate_sign((1,) * 6 if sign is None else sign)
        self.zero_offset_deg = self._six(
            (0.0,) * 6 if zero_offset_deg is None else zero_offset_deg
        )
        self.joint_mapping_known = sign is not None
        if (base_to_sofa_translation_mm is None) != (base_to_sofa_quaternion_xyzw is None):
            raise ValueError("Base-to-SOFA translation and quaternion must be provided together")
        self._sofa_from_base = (
            matrix_from_translation_quaternion(
                base_to_sofa_translation_mm, base_to_sofa_quaternion_xyzw
            )
            if base_to_sofa_translation_mm is not None
            and base_to_sofa_quaternion_xyzw is not None
            else None
        )
        self.coordinate_calibrated = self.joint_mapping_known and self._sofa_from_base is not None
        self.stale_ms = stale_ms
        self.kinematics = E05ProKinematics(
            joint_limits_deg=config.robot.joint_limits_deg,
            force_flange_offset_mm=config.robot.force_flange_offset_mm,
            tool_translation_mm=(0.0, 0.0, 0.0),
            tool_rpy_deg=(0.0, 0.0, 0.0),
        )
        self._trajectory_mm: deque[tuple[float, float, float]] = deque(
            maxlen=config.trajectory_history_limit
        )
        self._trajectory_sofa_mm: deque[tuple[float, float, float]] = deque(
            maxlen=config.trajectory_history_limit
        )
        self.snapshot: ExternalJointSnapshot | None = None
        self.freshness = SourceFreshness.DISCONNECTED
        self.reason = "no_actual_joint_sample"
        self._pending_session: str | None = None
        self._pending_sequence = -1

    @staticmethod
    def _six(values: Sequence[float]) -> tuple[float, float, float, float, float, float]:
        if isinstance(values, (str, bytes)) or len(values) != 6:
            raise ValueError("actual joint vector must contain exactly six values")
        if any(isinstance(value, bool) for value in values):
            raise ValueError("actual joint vector cannot contain booleans")
        result = tuple(float(value) for value in values)
        if not all(isfinite(value) for value in result):
            raise ValueError("actual joint vector must be finite")
        return result  # type: ignore[return-value]

    @staticmethod
    def _validate_sign(values: Sequence[int]) -> tuple[int, int, int, int, int, int]:
        if len(values) != 6 or any(type(value) is not int or value not in (-1, 1) for value in values):
            raise ValueError("joint sign must contain six +1/-1 integers")
        return tuple(values)  # type: ignore[return-value]

    @property
    def trajectory_mm(self) -> tuple[tuple[float, float, float], ...]:
        """Actual controller TCP samples in robot Base; never command targets."""
        return tuple(self._trajectory_mm)

    @property
    def trajectory_sofa_mm(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(self._trajectory_sofa_mm)

    def freeze(self, freshness: SourceFreshness, reason: str) -> None:
        self.freshness = freshness
        self.reason = reason

    def apply_external_joint_state(self, telemetry: RobotTelemetry) -> bool:
        """Return true only when a new validated actual sample changes the mirror."""
        if (
            telemetry.runtime_mode != RuntimeMode.REAL
            or telemetry.provider != RobotProvider.HUAYAN_EDGE_GATEWAY
            or telemetry.control_mode != "observe-only"
            or telemetry.controller_is_simulation is not False
        ):
            self.freeze(SourceFreshness.STALE, "not_observe_only_real_feedback")
            return False
        if telemetry.freshness != SourceFreshness.FRESH:
            self.freeze(telemetry.freshness, "source_not_fresh")
            return False
        if (
            telemetry.state_age_ms is None
            or not isfinite(telemetry.state_age_ms)
            or telemetry.state_age_ms < 0
            or telemetry.state_age_ms > self.stale_ms
        ):
            self.freeze(SourceFreshness.STALE, "source_age_exceeded")
            return False
        session = telemetry.gateway_session_id
        if not session or telemetry.joint_positions_deg is None or telemetry.actual_pose_robot_base is None:
            self.freeze(SourceFreshness.STALE, "incomplete_actual_feedback")
            return False
        if self.snapshot is not None and session != self.snapshot.gateway_session_id:
            if self._pending_session != session:
                self._pending_session = session
                self._pending_sequence = telemetry.sequence
                self.freeze(SourceFreshness.STALE, "new_session_waiting_for_next_sample")
                return False
            if telemetry.sequence <= self._pending_sequence:
                return False
        elif self.snapshot is not None:
            if telemetry.sequence < self.snapshot.source_sequence:
                self.freeze(SourceFreshness.STALE, "source_sequence_regressed")
                return False
            if telemetry.sequence == self.snapshot.source_sequence:
                return False
        try:
            actual = self._six(telemetry.joint_positions_deg)
            visual_deg = tuple(
                direction * (position - offset)
                for direction, position, offset in zip(self.sign, actual, self.zero_offset_deg)
            )
            visual_rad = tuple(float(value) for value in np.deg2rad(visual_deg))
            kinematics_robot_base = self.kinematics.forward(visual_rad)
            kinematics = (
                transform_snapshot(kinematics_robot_base, self._sofa_from_base)
                if self._sofa_from_base is not None
                else kinematics_robot_base
            )
            source_tcp = tuple(float(value) for value in telemetry.actual_pose_robot_base.translation_mm)
            if not all(isfinite(value) for value in source_tcp):
                raise ValueError("actual TCP must be finite")
            sofa_tcp = (
                transform_point(self._sofa_from_base, source_tcp)
                if self.coordinate_calibrated and self._sofa_from_base is not None
                else None
            )
        except (TypeError, ValueError) as error:
            self.freeze(SourceFreshness.STALE, f"invalid_actual_feedback:{error}")
            return False
        if self.snapshot is not None and session != self.snapshot.gateway_session_id:
            self._trajectory_mm.clear()
            self._trajectory_sofa_mm.clear()
        self.snapshot = ExternalJointSnapshot(
            source_sequence=telemetry.sequence,
            gateway_session_id=session,
            actual_joint_positions_deg=actual,
            visual_joint_positions_rad=visual_rad,  # type: ignore[arg-type]
            kinematics_robot_base=kinematics_robot_base,
            kinematics=kinematics,
            actual_tcp_robot_base_mm=source_tcp,  # type: ignore[arg-type]
            actual_tcp_sofa_world_mm=sofa_tcp,
        )
        self._pending_session = None
        self._pending_sequence = -1
        if not self._trajectory_mm or self._trajectory_mm[-1] != source_tcp:
            self._trajectory_mm.append(source_tcp)
        if sofa_tcp is not None and (
            not self._trajectory_sofa_mm or self._trajectory_sofa_mm[-1] != sofa_tcp
        ):
            self._trajectory_sofa_mm.append(sofa_tcp)
        self.freshness = SourceFreshness.FRESH
        self.reason = (
            "coordinate_calibrated_tool_tcp_unavailable"
            if self.coordinate_calibrated
            else "uncalibrated_visual_preview"
        )
        return True
