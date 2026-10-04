"""Mac-side execution of one authenticated, web-confirmed motion proposal."""

from __future__ import annotations

import time
from typing import Callable

from surgical_contracts import (
    ErrorCode,
    GatewayCommandKind,
    RobotCommandEnvelope,
    RobotCommandResult,
    RobotTelemetry,
    ToolStatus,
    command_fingerprint,
)

from .fake_motion import LocalMotionTrial
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
    feedback/readback and can be consumed only once by ``preflight_relative``.
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
        }:
            return self._failure(envelope, ErrorCode.OPERATION_NOT_ENABLED)
        if command_fingerprint(envelope) != fingerprint:
            return self._failure(envelope, ErrorCode.COMMAND_CONFLICT)
        if self._active or fingerprint in self._used_fingerprints:
            return self._failure(envelope, ErrorCode.COMMAND_CONFLICT)

        self._active = True
        self._used_fingerprints.add(fingerprint)
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
                return RobotCommandResult(
                    gateway_session_id=envelope.gateway_session_id,
                    command_id=envelope.command_id,
                    command_kind=envelope.command_kind,
                    status=ToolStatus.SUCCESS,
                    controller_waypoint_id=trial.waypoint_id,
                    final_pose_robot_base=final_sample.actual_pose_robot_base,
                )
            return self._failure(envelope, ErrorCode.ROBOT_TIMEOUT)
        except Exception:
            if trial is not None and trial.potentially_moving:
                trial.request_stop(reason="remote motion executor failed")
            return self._failure(envelope, ErrorCode.INTERNAL_ERROR)
        finally:
            self._active = False

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
