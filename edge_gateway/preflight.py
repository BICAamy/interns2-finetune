"""Pure, fail-closed motion checks for an isolated fake-controller trial.

No production entry point imports this module. A bare-flange real profile is
validated separately; fake approvals in this module never authorize it.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from typing import Callable, Literal

from surgical_contracts import (
    CoordinateFrame, DistanceUnit, GatewayCommandKind, LinkState,
    MoveRelativeRequest, Pose6D, RobotCommandEnvelope, RobotTelemetry,
    RuntimeMode, SourceFreshness,
)


def fingerprint(envelope: RobotCommandEnvelope) -> str:
    canonical = json.dumps(envelope.model_dump(mode="json"), sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class FakeMotionApproval:
    """Synthetic values only; never derived from an uncalibrated real config."""

    device_sn: str
    robot_model: str
    package_version: str
    config_sha256: str
    tcp_name: str
    ucs_name: Literal["Base"]
    tcp_xyzrpy: tuple[float, float, float, float, float, float]
    ucs_xyzrpy: tuple[float, float, float, float, float, float]
    payload_kg: float
    center_of_gravity_mm: tuple[float, float, float]
    base_installing_angle_deg: tuple[float, float]
    joint_soft_limits_deg: tuple[tuple[float, float], ...]
    joint_margin_deg: float
    workspace_low_mm: tuple[float, float, float]
    workspace_high_mm: tuple[float, float, float]
    max_speed_mm_s: float
    max_acceleration_mm_s2: float
    max_step_mm: float
    max_start_drift_mm: float
    max_start_rotation_deg: float
    state_stale_ms: float
    ready_fsm_code: int

    def __post_init__(self) -> None:
        if len(self.config_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.config_sha256):
            raise ValueError("invalid synthetic config digest")
        if not self.device_sn or not self.robot_model or not self.package_version or not self.tcp_name:
            raise ValueError("incomplete fake motion identity")
        if len(self.joint_soft_limits_deg) != 6:
            raise ValueError("fake joint limits require six axes")
        numeric = (
            *self.tcp_xyzrpy, *self.ucs_xyzrpy, self.payload_kg,
            *self.center_of_gravity_mm, *self.base_installing_angle_deg,
            *(v for pair in self.joint_soft_limits_deg for v in pair),
            self.joint_margin_deg, *self.workspace_low_mm, *self.workspace_high_mm,
            self.max_speed_mm_s, self.max_acceleration_mm_s2, self.max_step_mm,
            self.max_start_drift_mm, self.max_start_rotation_deg, self.state_stale_ms,
        )
        if any(not math.isfinite(value) for value in numeric):
            raise ValueError("fake motion limits must be finite")
        if any(value <= 0 for value in (
            self.joint_margin_deg, self.max_speed_mm_s, self.max_acceleration_mm_s2,
            self.max_step_mm, self.max_start_drift_mm, self.max_start_rotation_deg,
            self.state_stale_ms,
        )) or self.payload_kg < 0:
            raise ValueError("invalid fake motion limits")
        if any(low >= high for low, high in self.joint_soft_limits_deg) or any(
            low >= high for low, high in zip(self.workspace_low_mm, self.workspace_high_mm)
        ):
            raise ValueError("invalid fake motion bounds")


@dataclass(frozen=True)
class FakeControllerReadback:
    config_sha256: str
    tcp_name: str
    ucs_name: str
    tcp_xyzrpy: tuple[float, float, float, float, float, float]
    ucs_xyzrpy: tuple[float, float, float, float, float, float]
    payload_kg: float
    center_of_gravity_mm: tuple[float, float, float]
    base_installing_angle_deg: tuple[float, float]
    group_error_code: int
    axis_error_codes: tuple[int, int, int, int, int, int]
    active_program: bool
    waypoint_id: str


@dataclass
class MotionLease:
    owner: Literal["local", "remote"]
    session_id: str
    expires_monotonic_ns: int
    active: bool = True

    def revoke(self) -> None:
        self.active = False


class LocalArm:
    """May only be constructed from a displayed proposal by a Mac-local caller."""

    def __init__(
        self, *, test_id: str, command_fingerprint: str, session_id: str,
        base_sequence: int, safety_state_hash: str, expected_start: Pose6D,
        expires_monotonic_ns: int,
    ) -> None:
        if not all((test_id, command_fingerprint, session_id, safety_state_hash)):
            raise ValueError("ARM binding is incomplete")
        self.test_id = test_id
        self.command_fingerprint = command_fingerprint
        self.session_id = session_id
        self.base_sequence = base_sequence
        self.safety_state_hash = safety_state_hash
        self.expected_start = expected_start
        self.expires_monotonic_ns = expires_monotonic_ns
        self.used = False

    def revoke(self) -> None:
        self.used = True


class FakeExternalWriterGuard:
    """Withdraw a pending local ARM when fake feedback suggests another writer."""

    def __init__(
        self, *, arm: LocalArm, baseline: RobotTelemetry,
        baseline_waypoint_id: str, noise_threshold_mm: float,
    ) -> None:
        if baseline.actual_pose_robot_base is None or not baseline_waypoint_id:
            raise ValueError("external-writer baseline is incomplete")
        if not math.isfinite(noise_threshold_mm) or noise_threshold_mm <= 0:
            raise ValueError("noise threshold must be positive")
        self.arm = arm
        self.baseline = baseline
        self.baseline_waypoint_id = baseline_waypoint_id
        self.noise_threshold_mm = noise_threshold_mm

    def observe(self, snapshot: RobotTelemetry, *, waypoint_id: str) -> str | None:
        if self.arm.used:
            return "arm_inactive"
        reason = None
        if snapshot.freshness != SourceFreshness.FRESH or snapshot.gateway_session_id != self.baseline.gateway_session_id:
            reason = "feedback_lost"
        elif waypoint_id != self.baseline_waypoint_id:
            reason = "external_waypoint"
        elif snapshot.fsm_code != self.baseline.fsm_code or snapshot.moving is not False:
            reason = "unexpected_program_or_fsm"
        elif snapshot.actual_pose_robot_base is None or _distance(
            snapshot.actual_pose_robot_base.translation_mm,
            self.baseline.actual_pose_robot_base.translation_mm,
        ) > self.noise_threshold_mm:
            reason = "unowned_pose_change"
        if reason is not None:
            self.arm.revoke()
        return reason


def safety_state_hash(snapshot: RobotTelemetry, readback: FakeControllerReadback) -> str:
    fields = {
        "device_sn": snapshot.device_sn, "robot_model": snapshot.robot_model,
        "package_version": snapshot.package_version,
        "enabled": snapshot.enabled, "electrified": snapshot.electrified,
        "brakes_released": snapshot.brakes_released, "fsm_code": snapshot.fsm_code,
        "auto_mode": snapshot.auto_mode, "reduced_mode": snapshot.reduced_mode,
        "three_position_enable": snapshot.three_position_enable,
        "physical_estop_active": snapshot.physical_estop_active,
        "emergency_stop_circuit_fault": snapshot.emergency_stop_circuit_fault,
        "safeguard_active": snapshot.safeguard_active,
        "safeguard_circuit_fault": snapshot.safeguard_circuit_fault,
        "free_drive_active": snapshot.free_drive_active,
        "force_control_active": snapshot.force_control_active,
        "readback": readback.__dict__,
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _angle_deg(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = abs(sum(x * y for x, y in zip(a, b)))
    dot /= math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return math.degrees(2 * math.acos(min(1.0, max(-1.0, dot))))


def preflight_fake_relative(
    envelope: RobotCommandEnvelope, snapshot: RobotTelemetry,
    readback: FakeControllerReadback, approval: FakeMotionApproval,
    arm: LocalArm, leases: tuple[MotionLease, ...],
    path_ik: Callable[[tuple[float, float, float]], tuple[float, ...] | None],
    *, now_ms: int | None = None, now_monotonic_ns: int | None = None,
) -> Pose6D:
    """Return an absolute target without I/O; consume ARM only after every check."""
    now_ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
    now_monotonic_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    if envelope.command_kind != GatewayCommandKind.MOVE_RELATIVE or not isinstance(envelope.payload, MoveRelativeRequest):
        raise ValueError("fake trial supports only single-axis move_relative")
    if not envelope.created_at_ms <= now_ms < envelope.expires_at_ms:
        raise ValueError("motion envelope expired or has a future creation time")
    if snapshot.runtime_mode != RuntimeMode.REAL or snapshot.control_mode != "enabled":
        raise ValueError("synthetic enabled telemetry required for fake trial")
    if snapshot.freshness != SourceFreshness.FRESH or snapshot.state_age_ms is None or snapshot.state_age_ms > approval.state_stale_ms:
        raise ValueError("fake DataSheet is stale")
    if any(link != LinkState.CONNECTED for link in (
        snapshot.connections.gateway, snapshot.connections.datasheet,
        snapshot.connections.command_socket, snapshot.connections.controller_box,
    )):
        raise ValueError("fake connection is incomplete")
    if (snapshot.device_sn, snapshot.robot_model, snapshot.package_version) != (
        approval.device_sn, approval.robot_model, approval.package_version,
    ) or snapshot.controller_is_simulation is not False:
        raise ValueError("controller identity is not approved")
    safety_flags = (
        snapshot.enabled is True, snapshot.electrified is True,
        snapshot.brakes_released is True, snapshot.auto_mode is True,
        snapshot.reduced_mode is True, snapshot.three_position_enable is True,
        snapshot.physical_estop_active is False,
        snapshot.emergency_stop_circuit_fault is False,
        snapshot.safeguard_active is False,
        snapshot.safeguard_circuit_fault is False,
        snapshot.free_drive_active is False, snapshot.force_control_active is False,
        snapshot.moving is False, snapshot.in_position is True,
        snapshot.paused is False, snapshot.potentially_moving is False,
        snapshot.vendor_fault is None, snapshot.fsm_code == approval.ready_fsm_code,
    )
    if not all(safety_flags) or readback.active_program or readback.group_error_code != 0 or any(readback.axis_error_codes):
        raise ValueError("fake controller is not in approved ready state")
    if snapshot.active_command_id is not None:
        raise ValueError("another command is already active")
    if readback.tcp_name != approval.tcp_name or readback.ucs_name != approval.ucs_name:
        raise ValueError("TCP/UCS name changed")
    if readback.config_sha256 != approval.config_sha256:
        raise ValueError("loaded fake safety configuration changed")
    if any(_distance(a, b) > 1e-6 for a, b in (
        (readback.tcp_xyzrpy, approval.tcp_xyzrpy),
        (readback.ucs_xyzrpy, approval.ucs_xyzrpy),
        ((readback.payload_kg, *readback.center_of_gravity_mm),
         (approval.payload_kg, *approval.center_of_gravity_mm)),
        (readback.base_installing_angle_deg, approval.base_installing_angle_deg),
    )):
        raise ValueError("fake controller setup differs from approval")
    if envelope.expected_tcp_name != approval.tcp_name or envelope.expected_ucs_name != approval.ucs_name:
        raise ValueError("command TCP/UCS differs from approval")
    if envelope.safety_limits is None or envelope.safety_limits.max_speed_mm_s > approval.max_speed_mm_s or envelope.safety_limits.max_step_mm > approval.max_step_mm:
        raise ValueError("command requests unapproved limits")
    if envelope.payload.speed_mm_s > approval.max_speed_mm_s:
        raise ValueError("command speed exceeds approval")
    if len(leases) != 1 or not leases[0].active or leases[0].owner != "local" or leases[0].session_id != envelope.gateway_session_id or leases[0].expires_monotonic_ns <= now_monotonic_ns:
        raise ValueError("exclusive local commissioning lease missing")
    if snapshot.gateway_session_id != envelope.gateway_session_id or snapshot.sequence < envelope.based_on_robot_state_sequence:
        raise ValueError("source session or sequence changed")
    pose = snapshot.actual_pose_robot_base
    expected = envelope.expected_start_pose_robot_base
    if pose is None or expected is None or pose.frame != CoordinateFrame.ROBOT_BASE or pose.unit != DistanceUnit.MILLIMETER:
        raise ValueError("actual Base pose unavailable")
    if snapshot.joint_positions_deg is None:
        raise ValueError("actual joints unavailable")
    if any(not low + approval.joint_margin_deg <= value <= high - approval.joint_margin_deg
           for value, (low, high) in zip(snapshot.joint_positions_deg, approval.joint_soft_limits_deg)):
        raise ValueError("actual joints exceed approved margin")
    if _distance(pose.translation_mm, expected.translation_mm) > approval.max_start_drift_mm or _angle_deg(pose.quaternion_xyzw, expected.quaternion_xyzw) > approval.max_start_rotation_deg:
        raise ValueError("actual start drifted from proposal")
    if arm.used or now_monotonic_ns >= arm.expires_monotonic_ns or arm.test_id != envelope.operator_confirmation_id or arm.command_fingerprint != fingerprint(envelope) or arm.session_id != snapshot.gateway_session_id or snapshot.sequence < arm.base_sequence or arm.safety_state_hash != safety_state_hash(snapshot, readback) or _distance(pose.translation_mm, arm.expected_start.translation_mm) > approval.max_start_drift_mm or _angle_deg(pose.quaternion_xyzw, arm.expected_start.quaternion_xyzw) > approval.max_start_rotation_deg:
        raise ValueError("local single-use ARM is missing, stale, or mismatched")
    translation = tuple(float(value) for value in envelope.payload.translation_mm)
    if sum(abs(value) > 1e-12 for value in translation) != 1:
        raise ValueError("first fake motion supports exactly one Cartesian axis")
    if _distance((0, 0, 0), translation) > approval.max_step_mm:
        raise ValueError("relative step exceeds approval")
    target_xyz = tuple(float(a + b) for a, b in zip(pose.translation_mm, translation))
    # Both endpoints and intermediate points must pass workspace and IK checks.
    for index in range(11):
        ratio = index / 10
        point = tuple(float(a + ratio * b) for a, b in zip(pose.translation_mm, translation))
        if any(not low <= value <= high for value, low, high in zip(
            point, approval.workspace_low_mm, approval.workspace_high_mm
        )):
            raise ValueError("fake path leaves approved workspace")
        joints = path_ik(point)
        if joints is None or len(joints) != 6 or any(not math.isfinite(value) for value in joints):
            raise ValueError("fake path IK failed")
        if any(not low + approval.joint_margin_deg <= value <= high - approval.joint_margin_deg
               for value, (low, high) in zip(joints, approval.joint_soft_limits_deg)):
            raise ValueError("fake path crosses joint margin")
    arm.used = True
    return pose.model_copy(update={"translation_mm": target_xyz})
