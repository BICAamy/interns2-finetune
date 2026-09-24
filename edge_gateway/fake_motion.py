"""Local WayPoint lifecycle, exercised on fake before Mac commissioning.

The observe-only gateway and robot-runtime do not import this module. The
real writer itself requires a Mac-local interactive terminal.
"""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from typing import Callable

from surgical_contracts import (
    LinkState, MotionStopConfirmation, Pose6D, RobotCommandEnvelope,
    RobotProvider, RobotTelemetry, RuntimeMode, SoftwareStopResult,
    SourceFreshness, StopDelivery,
)

from .command_journal import CommandJournal, JournalError
from .huayan.command_codec import validate_identifier
from .huayan.fake_motion_client import FakeMotionClient
from .huayan.real_motion_client import LocalRealMotionClient
from .huayan.motion_codec import LinearWaypoint
from .preflight import (
    ControllerReadback, LocalArm, MotionApproval, MotionLease,
    fingerprint, preflight_relative, safety_state_hash,
)


@dataclass(frozen=True)
class LocalMotionTiming:
    response_ms: int
    start_ms: int
    motion_ms: int
    stop_confirmation_ms: int
    stable_samples: int
    dwell_ms: int
    position_tolerance_mm: float
    orientation_tolerance_deg: float

    def __post_init__(self) -> None:
        if any(value <= 0 for value in (
            self.response_ms, self.start_ms, self.motion_ms,
            self.stop_confirmation_ms, self.stable_samples, self.dwell_ms,
            self.position_tolerance_mm, self.orientation_tolerance_deg,
        )) or self.stable_samples < 2:
            raise ValueError("local motion deadlines and tolerances must be positive")


class LocalMotionTrial:
    """One active local command; acceptance cannot be mistaken for completion."""

    def __init__(
        self, *, client: FakeMotionClient | LocalRealMotionClient, journal: CommandJournal,
        timing: LocalMotionTiming, approval: MotionApproval,
        path_ik: Callable[[tuple[float, float, float]], tuple[float, ...] | None],
    ) -> None:
        if not isinstance(client, (FakeMotionClient, LocalRealMotionClient)):
            raise TypeError("local motion trial requires an approved typed client")
        if client.timeout_s * 1000 > timing.response_ms:
            raise ValueError("local socket timeout exceeds motion response deadline")
        self.client = client
        self.journal = journal
        self.timing = timing
        self.approval = approval
        self.path_ik = path_ik
        self.command_id: str | None = None
        self.waypoint_id: str | None = None
        self.target: Pose6D | None = None
        self.session_id: str | None = None
        self.sent_monotonic_ns: int | None = None
        self.last_feedback_monotonic_ns: int | None = None
        self.stop_monotonic_ns: int | None = None
        self.last_sequence: int = -1
        self.moving_seen = False
        self.stable_count = 0
        self.stable_since_ns: int | None = None
        self.stop_stable_count = 0
        self.stop_delivery: str | None = None
        self._lease: MotionLease | None = None
        self.external_writer_detected = False
        self._initial_auto_mode: bool | None = None
        self._initial_reduced_mode: bool | None = None
        self._stop_requests: dict[str, str] = {}
        self._last_stop_request_ns: int | None = None

    @property
    def potentially_moving(self) -> bool:
        if self.command_id is None:
            return False
        record = self.journal.record(self.command_id)
        return bool(record and record["potentially_moving"])

    @property
    def lease_active(self) -> bool:
        return bool(
            self._lease is not None and self._lease.active
            and time.monotonic_ns() < self._lease.expires_monotonic_ns
        )

    def submit(
        self, envelope: RobotCommandEnvelope, snapshot: RobotTelemetry,
        readback: ControllerReadback, arm: LocalArm,
        leases: tuple[MotionLease, ...], *, now_ms: int | None = None,
        now_monotonic_ns: int | None = None,
        final_guard: Callable[[], None] | None = None,
    ) -> str:
        if self.command_id is not None or self.journal.unresolved():
            raise JournalError("active or unresolved local command blocks submission")
        clock_injected = now_monotonic_ns is not None
        now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        try:
            target = preflight_relative(
                envelope, snapshot, readback, self.approval, arm, leases,
                self.path_ik, now_ms=now_ms, now_monotonic_ns=now_monotonic_ns,
            )
        except Exception:
            arm.revoke()
            raise
        if final_guard is not None:
            try:
                final_guard()
            except Exception:
                arm.revoke()
                raise
        send_now_ns = now_monotonic_ns if clock_injected else time.monotonic_ns()
        self._lease = leases[0]
        self._initial_auto_mode = snapshot.auto_mode
        self._initial_reduced_mode = snapshot.reduced_mode
        waypoint_id = "F" + hashlib.sha256(envelope.command_id.encode()).hexdigest()[:16]
        frame = LinearWaypoint(
            pose_xyzrpy=(*target.translation_mm, *target.rotation_rpy_deg),
            tcp_name=self.approval.tcp_name, ucs_name="Base",
            speed_mm_s=envelope.payload.speed_mm_s,
            acceleration_mm_s2=self.approval.max_acceleration_mm_s2,
            waypoint_id=waypoint_id,
            reference_joints_deg=snapshot.joint_positions_deg,
        )
        encoded = frame.encode()
        self.journal.prepare(
            command_id=envelope.command_id, fingerprint=fingerprint(envelope),
            session_id=envelope.gateway_session_id,
            safety_state_hash=safety_state_hash(snapshot, readback),
            start_sequence=snapshot.sequence, encoded_frame=encoded,
        )
        self.command_id = envelope.command_id
        self.waypoint_id = waypoint_id
        self.target = target
        self.session_id = envelope.gateway_session_id
        self.last_sequence = snapshot.sequence
        # This fsynced transition precedes the first byte. A crash afterwards
        # is ambiguous and must not cause an automatic replay.
        self.journal.transition(self.command_id, "send_started")
        self.sent_monotonic_ns = send_now_ns
        self.last_feedback_monotonic_ns = send_now_ns
        try:
            accepted = self.client.waypoint(frame)
        except BaseException:
            if self.journal.record(self.command_id)["state"] == "send_started":
                self.journal.transition(self.command_id, "unknown", evidence="write reply unavailable")
            self._lease.revoke()
            raise
        if self.journal.record(self.command_id)["state"] != "send_started":
            self._lease.revoke()
            raise JournalError("stop or fault raced with WayPoint reply; outcome remains uncertain")
        if not accepted:
            # A Fail reply is not proof of physical non-movement. Require
            # direct observation/reconciliation before another local trial.
            self.journal.transition(self.command_id, "unknown", evidence="vendor Fail reply; motion unverified")
            delivered = self.request_stop()
            return "stopping" if delivered == "sent" else "stop_unconfirmed"
        self.journal.transition(self.command_id, "accepted")
        return "accepted"

    def _feedback_is_safe(self, sample: RobotTelemetry) -> bool:
        return (
            sample.runtime_mode == RuntimeMode.REAL
            and sample.provider == RobotProvider.HUAYAN_EDGE_GATEWAY
            and sample.freshness == SourceFreshness.FRESH
            and sample.state_age_ms is not None
            and sample.state_age_ms <= self.approval.state_stale_ms
            and all(link == LinkState.CONNECTED for link in (
                sample.connections.gateway, sample.connections.datasheet,
                sample.connections.command_socket, sample.connections.controller_box,
            ))
            and sample.gateway_session_id == self.session_id
            and sample.device_sn == self.approval.device_sn
            and sample.controller_is_simulation is False
            and sample.enabled is True and sample.electrified is True
            # Before motion starts the E05-Pro may still hold its brakes. Once
            # moving, both feedback channels must agree that they are released.
            and not (sample.moving is True and sample.brakes_released is not True)
            and sample.auto_mode is self._initial_auto_mode
            and sample.reduced_mode is self._initial_reduced_mode
            and sample.free_drive_active is False
            and sample.force_control_active is False
            and sample.paused is False
            and sample.physical_estop_active is False
            and sample.emergency_stop_circuit_fault is False
            and sample.safeguard_active is False
            and sample.safeguard_circuit_fault is False
            and sample.vendor_fault is None
            and type(sample.moving) is bool
            and type(sample.in_position) is bool
            and sample.fsm_code is not None
            and not (sample.moving is True and sample.fsm_code == self.approval.ready_fsm_code)
        )

    def observe(self, sample: RobotTelemetry, *, now_monotonic_ns: int | None = None) -> str:
        if self.command_id is None or self.target is None or self.sent_monotonic_ns is None:
            raise RuntimeError("no local command has been submitted")
        now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        record = self.journal.record(self.command_id)
        if record is None:
            raise JournalError("active command missing from journal")
        if record["state"] in ("succeeded", "rejected", "stopped"):
            return record["state"]
        if sample.sequence <= self.last_sequence or not self._feedback_is_safe(sample):
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
            return "stopping" if self.stop_delivery == "sent" else "stop_unconfirmed"
        self.last_sequence = sample.sequence
        self.last_feedback_monotonic_ns = now_monotonic_ns
        if record["state"] in ("stopping", "stop_unconfirmed"):
            return self._observe_stop(sample, now_monotonic_ns)
        elapsed_ms = (now_monotonic_ns - self.sent_monotonic_ns) / 1_000_000
        if elapsed_ms > self.timing.motion_ms or (
            not self.moving_seen and elapsed_ms > self.timing.start_ms
        ):
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
            return "stopping" if self.stop_delivery == "sent" else "stop_unconfirmed"
        try:
            reported_id = self.client.current_waypoint_id()
        except Exception:
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
            return "stopping" if self.stop_delivery == "sent" else "stop_unconfirmed"
        if reported_id != self.waypoint_id:
            self.external_writer_detected = True
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
            return "stopping" if self.stop_delivery == "sent" else "stop_unconfirmed"
        if sample.moving is True:
            self.moving_seen = True
            self.stable_count = 0
            self.stable_since_ns = None
            if record["state"] == "accepted":
                self.journal.transition(self.command_id, "executing")
            return "executing"
        if not self.moving_seen:
            return "accepted"
        if (
            sample.in_position is not True
            or sample.fsm_code != self.approval.ready_fsm_code
            or sample.brakes_released is not False
        ):
            self.stable_count = 0
            self.stable_since_ns = None
            return "executing"
        pose = sample.actual_pose_robot_base
        if pose is None:
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
            return "stopping" if self.stop_delivery == "sent" else "stop_unconfirmed"
        position_error = math.dist(pose.translation_mm, self.target.translation_mm)
        dot = abs(sum(a*b for a, b in zip(pose.quaternion_xyzw, self.target.quaternion_xyzw)))
        angle_error = math.degrees(2 * math.acos(min(1.0, max(-1.0, dot))))
        if position_error > self.timing.position_tolerance_mm or angle_error > self.timing.orientation_tolerance_deg:
            self.stable_count = 0
            self.stable_since_ns = None
            return "executing"
        if self.stable_since_ns is None:
            self.stable_since_ns = now_monotonic_ns
        self.stable_count += 1
        if self.stable_count >= self.timing.stable_samples and (
            now_monotonic_ns - self.stable_since_ns
        ) / 1_000_000 >= self.timing.dwell_ms:
            self.journal.transition(self.command_id, "succeeded", evidence="owned ID, READY, InPos, stable pose")
            if self._lease is not None:
                self._lease.revoke()
            return "succeeded"
        return "executing"

    def request_stop(self, *, now_monotonic_ns: int | None = None) -> str:
        """Only this process's unresolved command may request ordinary TCP stop."""
        now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        if self.command_id is None or not self.potentially_moving:
            return "not_sent"
        if self._lease is not None:
            self._lease.revoke()
        record = self.journal.record(self.command_id)
        if record is None:
            return "not_sent"
        if record["state"] == "prepared":
            self.journal.transition(self.command_id, "not_sent", evidence="send-start marker absent")
            return "not_sent"
        if record["state"] in ("stopping", "stop_unconfirmed"):
            return self.stop_delivery or "unknown"
        self.journal.transition(self.command_id, "stopping")
        self.stop_monotonic_ns = now_monotonic_ns
        try:
            delivered = self.client.software_stop()
        except Exception:
            self.stop_delivery = "unknown"
            self.journal.transition(self.command_id, "stop_unconfirmed", evidence="stop delivery unknown")
            return self.stop_delivery
        self.stop_delivery = "sent" if delivered else "not_sent"
        if not delivered:
            self.journal.transition(self.command_id, "stop_unconfirmed", evidence="vendor rejected stop")
        return self.stop_delivery

    def request_authenticated_stop(
        self, stop_command_id: str, *, authenticated: bool,
        now_monotonic_ns: int | None = None,
    ) -> SoftwareStopResult:
        """Fake-only external stop API; watchdog uses request_stop directly."""
        validate_identifier(stop_command_id)
        if not authenticated:
            raise PermissionError("software stop requires authenticated caller")
        now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        previous = self._stop_requests.get(stop_command_id)
        if previous is not None:
            state = self.journal.record(self.command_id)["state"] if self.command_id else None
            return SoftwareStopResult(
                delivery=StopDelivery(previous),
                motion_stop=(MotionStopConfirmation.CONFIRMED if state == "stopped"
                             else MotionStopConfirmation.UNCONFIRMED),
            )
        if self._last_stop_request_ns is not None and (
            now_monotonic_ns - self._last_stop_request_ns < 200_000_000
        ):
            raise ValueError("software stop request rate limit")
        if len(self._stop_requests) >= 1024:
            raise JournalError("stop idempotency ledger full")
        self._last_stop_request_ns = now_monotonic_ns
        delivery = self.request_stop(now_monotonic_ns=now_monotonic_ns)
        bounded_delivery = delivery if delivery in ("sent", "not_sent", "unknown") else "unknown"
        self._stop_requests[stop_command_id] = bounded_delivery
        return SoftwareStopResult(
            delivery=StopDelivery(bounded_delivery),
            motion_stop=MotionStopConfirmation.UNCONFIRMED,
        )

    def _observe_stop(self, sample: RobotTelemetry, now_ns: int) -> str:
        if self.command_id is None or self.stop_monotonic_ns is None:
            raise JournalError("stop confirmation has no owned command")
        if (now_ns - self.stop_monotonic_ns) / 1_000_000 > self.timing.stop_confirmation_ms:
            if self.journal.record(self.command_id)["state"] == "stopping":
                self.journal.transition(self.command_id, "stop_unconfirmed", evidence="stop confirmation deadline")
            return "stop_unconfirmed"
        if self.stop_delivery != "sent":
            return "stop_unconfirmed"
        if self.external_writer_detected:
            if self.journal.record(self.command_id)["state"] == "stopping":
                self.journal.transition(self.command_id, "stop_unconfirmed", evidence="external waypoint ownership unknown")
            return "stop_unconfirmed"
        if (
            sample.moving is False
            and sample.fsm_code == self.approval.ready_fsm_code
            and sample.brakes_released is False
        ):
            self.stop_stable_count += 1
        else:
            self.stop_stable_count = 0
        if self.stop_stable_count >= 2:
            self.journal.transition(self.command_id, "stopped", evidence="two fresh nonmoving READY samples")
            return "stopped"
        return "stopping"

    def watchdog(self, *, now_monotonic_ns: int | None = None) -> str:
        """Finite deadline check even when no DataSheet sample arrives."""
        if self.command_id is None or not self.potentially_moving:
            return "idle"
        now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
        record = self.journal.record(self.command_id)
        if record is None:
            raise JournalError("active command missing from journal")
        if record["state"] in ("stopping", "stop_unconfirmed"):
            if self.stop_monotonic_ns is not None and (
                now_monotonic_ns - self.stop_monotonic_ns
            ) / 1_000_000 > self.timing.stop_confirmation_ms and record["state"] == "stopping":
                self.journal.transition(self.command_id, "stop_unconfirmed", evidence="no fresh stop confirmation")
        elif (
            self.last_feedback_monotonic_ns is not None
            and (now_monotonic_ns - self.last_feedback_monotonic_ns) / 1_000_000 > self.approval.state_stale_ms
        ) or (
            self.sent_monotonic_ns is not None
            and (now_monotonic_ns - self.sent_monotonic_ns) / 1_000_000 > self.timing.motion_ms
        ):
            self.request_stop(now_monotonic_ns=now_monotonic_ns)
        record = self.journal.record(self.command_id)
        return record["state"] if record else "unknown"


FakeMotionTiming = LocalMotionTiming
FakeMotionTrial = LocalMotionTrial
