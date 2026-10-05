"""Mac-side execution of one authenticated, web-confirmed motion proposal."""

from __future__ import annotations

import time
from typing import Callable

from surgical_contracts import (
    ErrorCode,
    GatewayCommandKind,
    MoveCartesianPoseRequest,
    MoveJointRelativeRequest,
    MoveRelativeRequest,
    MoveSequenceRequest,
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
            child_ttl_ms = envelope.expires_at_ms - envelope.created_at_ms
            final: RobotCommandResult | None = None
            for index, step in enumerate(request.steps):
                snapshot = self._snapshot()
                pose = snapshot.actual_pose_robot_base
                if pose is None:
                    raise ValueError("actual Base pose is unavailable")
                child_id = f"{envelope.command_id[:116]}-s{index + 1:02d}"
                if step.kind == MotionStepKind.CARTESIAN_RELATIVE:
                    assert step.translation_mm is not None
                    payload = MoveRelativeRequest(
                        command_id=child_id,
                        translation_mm=step.translation_mm,
                        frame=step.frame,
                        speed_mm_s=request.translation_speed_mm_s,
                    )
                    kind = GatewayCommandKind.MOVE_RELATIVE
                elif step.kind == MotionStepKind.CARTESIAN_ABSOLUTE:
                    assert step.target_position_mm is not None
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
                    assert step.joint_index is not None
                    if snapshot.joint_positions_deg is None:
                        raise ValueError("actual joint feedback is unavailable")
                    rotation = (
                        float(step.rotation_deg)
                        if step.kind == MotionStepKind.JOINT_RELATIVE
                        else float(step.target_angle_deg)
                        - float(snapshot.joint_positions_deg[step.joint_index - 1])
                    )
                    if abs(rotation) <= 1e-9:
                        continue
                    payload = MoveJointRelativeRequest(
                        command_id=child_id,
                        joint_index=step.joint_index,
                        rotation_deg=rotation,
                        speed_deg_s=request.joint_speed_deg_s,
                        acceleration_deg_s2=request.joint_acceleration_deg_s2,
                    )
                    kind = GatewayCommandKind.MOVE_JOINT_RELATIVE
                else:
                    assert step.rotation_axis is not None
                    rpy = list(float(value) for value in pose.rotation_rpy_deg)
                    axis_index = {"x": 0, "y": 1, "z": 2}[step.rotation_axis.value]
                    if step.kind == MotionStepKind.TCP_ROTATION_RELATIVE:
                        assert step.rotation_deg is not None
                        rpy[axis_index] += float(step.rotation_deg)
                    else:
                        assert step.target_angle_deg is not None
                        rpy[axis_index] = float(step.target_angle_deg)
                    target_rpy = tuple(rpy)
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
                child = RobotCommandEnvelope(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=child_id,
                    command_kind=kind,
                    created_at_ms=now_ms,
                    # The parent TTL is the browser-confirmation/dispatch
                    # deadline.  Once this confirmed sequence has started,
                    # each serial child gets the same fresh local preflight
                    # window so a long earlier step cannot expire a later one.
                    expires_at_ms=now_ms + child_ttl_ms,
                    based_on_robot_state_sequence=snapshot.sequence,
                    expected_start_pose_robot_base=pose,
                    expected_tcp_name=envelope.expected_tcp_name,
                    expected_ucs_name=envelope.expected_ucs_name,
                    payload=payload,
                    safety_limits=envelope.safety_limits,
                    operator_confirmation_id=envelope.operator_confirmation_id,
                )
                final = self._execute_one(child, command_fingerprint(child))
                if final.status != ToolStatus.SUCCESS:
                    return self._failure(
                        envelope,
                        final.error_code or ErrorCode.INTERNAL_ERROR,
                    )
            if final is None:
                snapshot = self._snapshot()
                return RobotCommandResult(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=envelope.command_id,
                    command_kind=envelope.command_kind,
                    status=ToolStatus.SUCCESS,
                    final_pose_robot_base=snapshot.actual_pose_robot_base,
                    final_joint_positions_deg=snapshot.joint_positions_deg,
                )
            return RobotCommandResult(
                gateway_session_id=envelope.gateway_session_id,
                command_id=envelope.command_id,
                command_kind=envelope.command_kind,
                status=ToolStatus.SUCCESS,
                controller_waypoint_id=final.controller_waypoint_id,
                final_pose_robot_base=final.final_pose_robot_base,
                final_joint_positions_deg=final.final_joint_positions_deg,
            )
        except Exception:
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)
        finally:
            self._active = False

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
            last_sequence = snapshot.sequence
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
        except Exception:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="remote motion executor failed")
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)

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
