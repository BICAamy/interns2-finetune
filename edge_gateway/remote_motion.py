"""Mac-side execution of one authenticated, web-confirmed motion proposal."""

from __future__ import annotations

import hashlib
import math
import time
from typing import Callable

from surgical_contracts import (
    ErrorCode,
    GatewayCommandKind,
    MoveCartesianPoseRequest,
    MoveJointRelativeRequest,
    MoveRelativeRequest,
    MoveSequenceRequest,
    MotionSequenceStep,
    MotionStepKind,
    RobotCommandEnvelope,
    RobotCommandResult,
    RobotTelemetry,
    ToolStatus,
    command_fingerprint,
)

from .fake_motion import LocalMotionTrial
from .huayan.adapter import fixed_xyz_quaternion
from .preflight import (
    ControllerReadback,
    LocalArm,
    MotionLease,
    PreflightTarget,
    preflight_motion,
    safety_state_hash,
)


class RemoteMotionExecutor:
    """Create and consume a Mac-local ARM without a second terminal prompt.

    The authenticated command frame proves that the browser confirmed this
    exact fingerprint.  The ARM is still local state, is bound to the newest
    feedback/readback and can be consumed only once by ``preflight_motion``.
    """

    def __init__(
        self,
        *,
        trial_factory: Callable[[], LocalMotionTrial],
        snapshot: Callable[[], RobotTelemetry],
        readback: Callable[[], ControllerReadback],
        feedback: Callable[[], tuple[RobotTelemetry, str | None]],
        poll_interval_s: float = 0.02,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("remote motion poll interval must be positive")
        self._trial_factory = trial_factory
        self._snapshot = snapshot
        self._readback = readback
        self._feedback = feedback
        self._poll_interval_s = poll_interval_s
        self._used_fingerprints: set[str] = set()
        self._active = False

    def execute(
        self, envelope: RobotCommandEnvelope, fingerprint: str,
    ) -> RobotCommandResult:
        if envelope.command_kind not in {
            GatewayCommandKind.MOVE_RELATIVE,
            GatewayCommandKind.MOVE_TO_ENTRY,
            GatewayCommandKind.MOVE_SEQUENCE,
        }:
            return self._failure(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        if command_fingerprint(envelope) != fingerprint:
            return self._failure(envelope, ErrorCode.COMMAND_CONFLICT)
        started_at_ms = time.time_ns() // 1_000_000
        if not envelope.created_at_ms <= started_at_ms < envelope.expires_at_ms:
            return self._failure(envelope, ErrorCode.COMMAND_EXPIRED)
        if self._active or fingerprint in self._used_fingerprints:
            return self._failure(envelope, ErrorCode.COMMAND_CONFLICT)

        self._active = True
        self._used_fingerprints.add(fingerprint)
        try:
            if envelope.command_kind != GatewayCommandKind.MOVE_SEQUENCE:
                return self._execute_one(envelope, fingerprint)
            request = envelope.payload
            if not isinstance(request, MoveSequenceRequest):
                return self._failure(envelope, ErrorCode.INVALID_COMMAND_SCHEMA)
            return self._execute_continuous_sequence(envelope, request)
        except Exception:
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)
        finally:
            self._active = False

    def _execute_continuous_sequence(
        self,
        envelope: RobotCommandEnvelope,
        request: MoveSequenceRequest,
    ) -> RobotCommandResult:
        """Preflight the complete path, queue it once, then verify only its end.

        Intermediate points are controller blending points. They are not
        treated as separate commands and therefore have no READY/InPos/dwell
        gate. Safety feedback remains monitored for the whole sequence.
        """
        trial: LocalMotionTrial | None = None
        try:
            start = self._snapshot()
            readback = self._readback()
            if start.actual_pose_robot_base is None:
                raise ValueError("actual Base pose is unavailable")
            remaining_ms = envelope.expires_at_ms - time.time_ns() // 1_000_000
            if remaining_ms <= 0:
                return self._failure(envelope, ErrorCode.COMMAND_EXPIRED)
            expires_ns = time.monotonic_ns() + remaining_ms * 1_000_000
            lease = MotionLease(
                owner="remote",
                session_id=envelope.gateway_session_id,
                expires_monotonic_ns=expires_ns,
            )
            trial = self._trial_factory()
            predicted = start
            planned: list[
                tuple[RobotCommandEnvelope, RobotTelemetry, PreflightTarget]
            ] = []
            for index, step in enumerate(request.steps):
                child = self._sequence_child(
                    envelope, request, step, index=index, start=predicted,
                )
                if child is None:
                    continue
                pose = predicted.actual_pose_robot_base
                if pose is None:
                    raise ValueError("predicted Base pose is unavailable")
                arm = LocalArm(
                    test_id=child.operator_confirmation_id or "",
                    command_fingerprint=command_fingerprint(child),
                    session_id=child.gateway_session_id,
                    base_sequence=predicted.sequence,
                    safety_state_hash=safety_state_hash(predicted, readback),
                    expected_start=pose,
                    expires_monotonic_ns=expires_ns,
                )
                target = preflight_motion(
                    child,
                    predicted,
                    readback,
                    trial.approval,
                    arm,
                    (lease,),
                    trial.path_ik,
                    trial.joint_fk,
                    required_lease_owner="remote",
                )
                planned.append((child, predicted, target))
                predicted = predicted.model_copy(update={
                    "actual_pose_robot_base": target.pose,
                    "joint_positions_deg": target.joint_positions_deg,
                    "moving": False,
                    "in_position": True,
                    "potentially_moving": False,
                    "fsm_code": trial.approval.ready_fsm_code,
                    "active_command_id": None,
                    "controller_waypoint_id": None,
                })
            if not planned:
                return RobotCommandResult(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=envelope.command_id,
                    command_kind=envelope.command_kind,
                    status=ToolStatus.SUCCESS,
                    final_pose_robot_base=start.actual_pose_robot_base,
                    final_joint_positions_deg=start.joint_positions_deg,
                )
            frames = tuple(
                trial.make_waypoint(
                    child,
                    segment_start,
                    target,
                    waypoint_id=(
                        "F"
                        + hashlib.sha256(child.command_id.encode()).hexdigest()[:16]
                    ),
                    blend_radius_mm=(
                        trial.approval.sequence_blend_radius_mm
                        if index < len(planned) - 1
                        else 0.0
                    ),
                )
                for index, (child, segment_start, target) in enumerate(planned)
            )

            # One fresh guard after full-path planning; there is deliberately
            # no stop/readback/preflight cycle between individual points.
            fresh = self._snapshot()
            fresh_readback = self._readback()
            self._verify_sequence_start_unchanged(
                start, readback, fresh, fresh_readback, trial,
            )
            state = trial.submit_preflighted_sequence(
                envelope,
                fresh,
                fresh_readback,
                lease,
                frames,
                planned[-1][2],
            )
            return self._wait_for_trial(envelope, trial, state, fresh.sequence)
        except Exception:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="continuous remote sequence failed")
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)

    def _sequence_child(
        self,
        parent: RobotCommandEnvelope,
        request: MoveSequenceRequest,
        step: MotionSequenceStep,
        *,
        index: int,
        start: RobotTelemetry,
    ) -> RobotCommandEnvelope | None:
        pose = start.actual_pose_robot_base
        if pose is None:
            raise ValueError("actual Base pose is unavailable")
        child_id = f"{parent.command_id[:116]}-s{index + 1:02d}"
        if step.kind == MotionStepKind.CARTESIAN_RELATIVE:
            payload = MoveRelativeRequest(
                command_id=child_id,
                translation_mm=step.translation_mm,
                frame=step.frame,
                speed_mm_s=request.translation_speed_mm_s,
            )
            kind = GatewayCommandKind.MOVE_RELATIVE
        elif step.kind == MotionStepKind.CARTESIAN_ABSOLUTE:
            payload = MoveCartesianPoseRequest(
                command_id=child_id,
                target_pose_robot_base=pose.model_copy(
                    update={"translation_mm": step.target_position_mm}
                ),
                speed_mm_s=request.translation_speed_mm_s,
            )
            kind = GatewayCommandKind.MOVE_CARTESIAN_POSE
        elif step.kind in {
            MotionStepKind.JOINT_RELATIVE,
            MotionStepKind.JOINT_ABSOLUTE,
        }:
            if start.joint_positions_deg is None:
                raise ValueError("actual joint feedback is unavailable")
            rotation = (
                float(step.rotation_deg)
                if step.kind == MotionStepKind.JOINT_RELATIVE
                else float(step.target_angle_deg)
                - float(start.joint_positions_deg[step.joint_index - 1])
            )
            if abs(rotation) <= 1e-9:
                return None
            payload = MoveJointRelativeRequest(
                command_id=child_id,
                joint_index=step.joint_index,
                rotation_deg=rotation,
                speed_deg_s=request.joint_speed_deg_s,
                acceleration_deg_s2=request.joint_acceleration_deg_s2,
            )
            kind = GatewayCommandKind.MOVE_JOINT_RELATIVE
        else:
            rpy = list(float(value) for value in pose.rotation_rpy_deg)
            axis_index = {"x": 0, "y": 1, "z": 2}[step.rotation_axis.value]
            if step.kind == MotionStepKind.TCP_ROTATION_RELATIVE:
                rpy[axis_index] += float(step.rotation_deg)
            else:
                rpy[axis_index] = float(step.target_angle_deg)
            target_rpy = tuple(rpy)
            if all(abs(a - b) <= 1e-9 for a, b in zip(
                target_rpy, pose.rotation_rpy_deg,
            )):
                return None
            payload = MoveCartesianPoseRequest(
                command_id=child_id,
                target_pose_robot_base=pose.model_copy(update={
                    "rotation_rpy_deg": target_rpy,
                    "quaternion_xyzw": fixed_xyz_quaternion(target_rpy),
                }),
                speed_mm_s=request.translation_speed_mm_s,
            )
            kind = GatewayCommandKind.MOVE_CARTESIAN_POSE
        now_ms = time.time_ns() // 1_000_000
        return RobotCommandEnvelope(
            gateway_session_id=parent.gateway_session_id,
            command_id=child_id,
            command_kind=kind,
            created_at_ms=now_ms,
            expires_at_ms=parent.expires_at_ms,
            based_on_robot_state_sequence=start.sequence,
            expected_start_pose_robot_base=pose,
            expected_tcp_name=parent.expected_tcp_name,
            expected_ucs_name=parent.expected_ucs_name,
            payload=payload,
            safety_limits=parent.safety_limits,
            operator_confirmation_id=parent.operator_confirmation_id,
        )

    @staticmethod
    def _verify_sequence_start_unchanged(
        before: RobotTelemetry,
        before_readback: ControllerReadback,
        after: RobotTelemetry,
        after_readback: ControllerReadback,
        trial: LocalMotionTrial,
    ) -> None:
        a = before.actual_pose_robot_base
        b = after.actual_pose_robot_base
        if a is None or b is None:
            raise ValueError("actual Base pose became unavailable")
        if before.gateway_session_id != after.gateway_session_id:
            raise ValueError("gateway session changed while planning")
        if safety_state_hash(before, before_readback) != safety_state_hash(
            after, after_readback,
        ):
            raise ValueError("safety state changed while planning")
        if math.dist(a.translation_mm, b.translation_mm) > trial.approval.max_start_drift_mm:
            raise ValueError("actual start position changed while planning")
        dot = abs(sum(x * y for x, y in zip(a.quaternion_xyzw, b.quaternion_xyzw)))
        angle = math.degrees(2 * math.acos(min(1.0, max(-1.0, dot))))
        if angle > trial.approval.max_start_rotation_deg:
            raise ValueError("actual start orientation changed while planning")

    def _execute_one(
        self,
        envelope: RobotCommandEnvelope,
        fingerprint: str,
    ) -> RobotCommandResult:
        trial: LocalMotionTrial | None = None
        try:
            snapshot = self._snapshot()
            readback = self._readback()
            pose = snapshot.actual_pose_robot_base
            if pose is None:
                raise ValueError("actual Base pose is unavailable")
            remaining_ms = envelope.expires_at_ms - time.time_ns() // 1_000_000
            if remaining_ms <= 0:
                return self._failure(envelope, ErrorCode.COMMAND_EXPIRED)
            expires_ns = time.monotonic_ns() + remaining_ms * 1_000_000
            arm = LocalArm(
                test_id=envelope.operator_confirmation_id or "",
                command_fingerprint=fingerprint,
                session_id=envelope.gateway_session_id,
                base_sequence=snapshot.sequence,
                safety_state_hash=safety_state_hash(snapshot, readback),
                expected_start=pose,
                expires_monotonic_ns=expires_ns,
            )
            lease = MotionLease(
                owner="remote",
                session_id=envelope.gateway_session_id,
                expires_monotonic_ns=expires_ns,
            )
            trial = self._trial_factory()
            state = trial.submit(
                envelope,
                snapshot,
                readback,
                arm,
                (lease,),
                required_lease_owner="remote",
            )
            return self._wait_for_trial(
                envelope, trial, state, snapshot.sequence,
            )
        except Exception:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="remote motion executor failed")
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)

    def _wait_for_trial(
        self,
        envelope: RobotCommandEnvelope,
        trial: LocalMotionTrial,
        state: str,
        last_sequence: int,
    ) -> RobotCommandResult:
        while state not in {
            "succeeded", "failed", "rejected", "stopped", "stop_unconfirmed",
        }:
            time.sleep(self._poll_interval_s)
            sample, debug = self._feedback()
            if sample.sequence <= last_sequence:
                continue
            last_sequence = sample.sequence
            state = trial.observe(sample, feedback_debug=debug)
        final_sample, _debug = self._feedback()
        if state == "succeeded":
            prepare_next = getattr(trial.client, "prepare_next_waypoint", None)
            if prepare_next is not None:
                prepare_next(stationary_confirmed=True)
            return RobotCommandResult(
                gateway_session_id=envelope.gateway_session_id,
                command_id=envelope.command_id,
                command_kind=envelope.command_kind,
                status=ToolStatus.SUCCESS,
                controller_waypoint_id=trial.waypoint_id,
                final_pose_robot_base=final_sample.actual_pose_robot_base,
                final_joint_positions_deg=final_sample.joint_positions_deg,
            )
        return self._failure(envelope, ErrorCode.ROBOT_TIMEOUT)

    @staticmethod
    def _failure(
        envelope: RobotCommandEnvelope, error_code: ErrorCode,
    ) -> RobotCommandResult:
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=error_code,
        )
