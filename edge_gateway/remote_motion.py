"""Mac-side execution of one authenticated, web-confirmed motion proposal."""

from __future__ import annotations

import hashlib
import math
import threading
import time
from typing import Callable

from surgical_contracts import (
    ErrorCode,
    GatewayCommandKind,
    MoveCartesianPoseRequest,
    MoveJointRelativeRequest,
    MoveRelativeRequest,
    MoveSequenceRequest,
    MotionStopConfirmation,
    MotionSequenceStep,
    MotionStepKind,
    RobotCommandEnvelope,
    RobotCommandResult,
    RobotTelemetry,
    SoftwareStopResult,
    StopDelivery,
    ToolStatus,
    command_fingerprint,
)

from .command_journal import JournalError
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
        local_preflight_timeout_ms: int = 120_000,
    ) -> None:
        if poll_interval_s <= 0:
            raise ValueError("remote motion poll interval must be positive")
        if local_preflight_timeout_ms <= 0:
            raise ValueError("local preflight timeout must be positive")
        self._trial_factory = trial_factory
        self._snapshot = snapshot
        self._readback = readback
        self._feedback = feedback
        self._poll_interval_s = poll_interval_s
        self._local_preflight_timeout_ms = local_preflight_timeout_ms
        self._used_fingerprints: set[str] = set()
        self._active = False
        self._trial_lock = threading.RLock()
        self._active_trial: LocalMotionTrial | None = None
        self._terminal_state: str | None = None
        self._done = threading.Event()

    def execute(
        self,
        envelope: RobotCommandEnvelope,
        fingerprint: str,
        *,
        local_deadline_monotonic_ns: int | None = None,
    ) -> RobotCommandResult:
        if envelope.command_kind not in {
            GatewayCommandKind.MOVE_RELATIVE,
            GatewayCommandKind.MOVE_TO_ENTRY,
            GatewayCommandKind.MOVE_SEQUENCE,
        }:
            return self._failure(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        if command_fingerprint(envelope) != fingerprint:
            return self._failure(envelope, ErrorCode.COMMAND_CONFLICT)
        if self._active or fingerprint in self._used_fingerprints:
            return self._failure(
                envelope,
                ErrorCode.COMMAND_CONFLICT,
                "motion fingerprint is already active or has already been consumed",
            )

        if local_deadline_monotonic_ns is None:
            local_deadline_monotonic_ns = (
                time.monotonic_ns()
                + self._local_preflight_timeout_ms * 1_000_000
            )
        if time.monotonic_ns() >= local_deadline_monotonic_ns:
            return self._failure(
                envelope,
                ErrorCode.ROBOT_TIMEOUT,
                "Mac-local preflight deadline expired before execution began",
            )

        self._active = True
        self._terminal_state = None
        self._done.clear()
        self._used_fingerprints.add(fingerprint)
        try:
            if envelope.command_kind != GatewayCommandKind.MOVE_SEQUENCE:
                return self._execute_one(
                    envelope,
                    fingerprint,
                    local_deadline_monotonic_ns,
                )
            request = envelope.payload
            if not isinstance(request, MoveSequenceRequest):
                return self._failure(envelope, ErrorCode.INVALID_COMMAND_SCHEMA)
            return self._execute_continuous_sequence(
                envelope,
                request,
                local_deadline_monotonic_ns,
            )
        except Exception as exc:
            return self._exception_failure(envelope, exc)
        finally:
            self._active = False
            self._done.set()

    def request_authenticated_stop(
        self,
        stop_command_id: str,
        *,
        timeout_s: float,
    ) -> SoftwareStopResult:
        """Interrupt the currently owned motion through its existing 10003 client.

        The stop shares the active trial instead of opening another controller
        socket.  Completion is reported only after the motion worker observes
        fresh stationary READY feedback.
        """

        if timeout_s <= 0:
            raise ValueError("software stop timeout must be positive")
        with self._trial_lock:
            trial = self._active_trial
            if trial is None or not trial.potentially_moving:
                return SoftwareStopResult(
                    delivery=StopDelivery.NOT_SENT,
                    motion_stop=MotionStopConfirmation.UNCONFIRMED,
                )
            requested = trial.request_authenticated_stop(
                stop_command_id,
                authenticated=True,
            )
        if requested.delivery != StopDelivery.SENT:
            return requested
        if not self._done.wait(timeout_s):
            return SoftwareStopResult(
                delivery=StopDelivery.SENT,
                motion_stop=MotionStopConfirmation.UNCONFIRMED,
            )
        return SoftwareStopResult(
            delivery=StopDelivery.SENT,
            motion_stop=(
                MotionStopConfirmation.CONFIRMED
                if self._terminal_state == "stopped"
                else MotionStopConfirmation.UNCONFIRMED
            ),
        )

    def _execute_continuous_sequence(
        self,
        envelope: RobotCommandEnvelope,
        request: MoveSequenceRequest,
        local_deadline_monotonic_ns: int,
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
            expires_ns = local_deadline_monotonic_ns
            if time.monotonic_ns() >= expires_ns:
                raise TimeoutError("Mac-local preflight deadline expired")
            lease = MotionLease(
                owner="remote",
                session_id=envelope.gateway_session_id,
                expires_monotonic_ns=expires_ns,
            )
            trial = self._trial_factory()
            with self._trial_lock:
                self._active_trial = trial
            predicted = start
            planned: list[
                tuple[RobotCommandEnvelope, RobotTelemetry, PreflightTarget]
            ] = []
            for index, step in enumerate(request.steps):
                if time.monotonic_ns() >= expires_ns:
                    raise TimeoutError(
                        "Mac-local preflight deadline expired while checking sequence"
                    )
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
                    enforce_envelope_deadline=False,
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
            if time.monotonic_ns() >= expires_ns:
                raise TimeoutError(
                    "Mac-local preflight deadline expired before WayPoint submission"
                )
            fresh = self._snapshot()
            fresh_readback = self._readback()
            self._verify_sequence_start_unchanged(
                start, readback, fresh, fresh_readback, trial,
            )
            with self._trial_lock:
                state = trial.submit_preflighted_sequence(
                    envelope,
                    fresh,
                    fresh_readback,
                    lease,
                    frames,
                    planned[-1][2],
                )
            return self._wait_for_trial(envelope, trial, state, fresh.sequence)
        except Exception as exc:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="continuous remote sequence failed")
            return self._exception_failure(envelope, exc)
        finally:
            with self._trial_lock:
                if self._active_trial is trial:
                    self._active_trial = None

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
        return RobotCommandEnvelope(
            gateway_session_id=parent.gateway_session_id,
            command_id=child_id,
            command_kind=kind,
            # Child envelopes inherit the proposal's immutable wire timestamps.
            # Their execution is governed by the independent Mac monotonic
            # deadline after the parent has arrived in time.
            created_at_ms=parent.created_at_ms,
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
        local_deadline_monotonic_ns: int,
    ) -> RobotCommandResult:
        trial: LocalMotionTrial | None = None
        try:
            snapshot = self._snapshot()
            readback = self._readback()
            pose = snapshot.actual_pose_robot_base
            if pose is None:
                raise ValueError("actual Base pose is unavailable")
            expires_ns = local_deadline_monotonic_ns
            if time.monotonic_ns() >= expires_ns:
                raise TimeoutError("Mac-local preflight deadline expired")
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
            with self._trial_lock:
                self._active_trial = trial
            with self._trial_lock:
                state = trial.submit(
                    envelope,
                    snapshot,
                    readback,
                    arm,
                    (lease,),
                    required_lease_owner="remote",
                    enforce_envelope_deadline=False,
                )
            return self._wait_for_trial(
                envelope, trial, state, snapshot.sequence,
            )
        except Exception as exc:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="remote motion executor failed")
            return self._exception_failure(envelope, exc)
        finally:
            with self._trial_lock:
                if self._active_trial is trial:
                    self._active_trial = None

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
            with self._trial_lock:
                state = trial.observe(sample, feedback_debug=debug)
        self._terminal_state = state
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
        detail = trial.stop_reason or f"local motion ended in state {state}"
        if trial.last_feedback_debug:
            detail = f"{detail}; {trial.last_feedback_debug}"
        return self._failure(envelope, ErrorCode.ROBOT_TIMEOUT, detail)

    @classmethod
    def _exception_failure(
        cls,
        envelope: RobotCommandEnvelope,
        exc: Exception,
    ) -> RobotCommandResult:
        message = f"{type(exc).__name__}: {exc}"[:512]
        lowered = str(exc).lower()
        if isinstance(exc, TimeoutError) or "timeout" in lowered or "deadline" in lowered:
            code = ErrorCode.ROBOT_TIMEOUT
        elif isinstance(exc, JournalError) or any(
            marker in lowered
            for marker in ("active or unresolved", "already active", "already used")
        ):
            code = ErrorCode.COMMAND_CONFLICT
        elif "workspace" in lowered:
            code = ErrorCode.OUT_OF_WORKSPACE
        elif " ik" in f" {lowered}" or "inverse kinematic" in lowered:
            code = ErrorCode.IK_FAILED
        elif any(
            marker in lowered
            for marker in ("wrong payload", "wrong command", "schema", "requires base/mm")
        ):
            code = ErrorCode.INVALID_COMMAND_SCHEMA
        elif isinstance(exc, ValueError) or isinstance(exc, PermissionError):
            code = ErrorCode.OPERATION_NOT_ENABLED
        else:
            code = ErrorCode.INTERNAL_ERROR
        return cls._failure(envelope, code, message)

    @staticmethod
    def _failure(
        envelope: RobotCommandEnvelope,
        error_code: ErrorCode,
        error_message: str | None = None,
    ) -> RobotCommandResult:
        return RobotCommandResult(
            gateway_session_id=envelope.gateway_session_id,
            command_id=envelope.command_id,
            command_kind=envelope.command_kind,
            status=ToolStatus.FAILED,
            error_code=error_code,
            error_message=(error_message or error_code.value)[:512],
        )
