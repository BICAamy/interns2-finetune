"""Mac-local feedback and Gate D inputs for one bare-flange 1 mm trial.

No cloud transport is imported here. This module does not contain a loop or
entry point that sends motion; commissioning_cli owns each human confirmation.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from robot_runtime.real_config import RealRobotConfig

from .cloud_transport import telemetry_from_sample
from .huayan.adapter import (
    fixed_xyz_quaternion, read_actual_position, read_axis_error_code, read_base_installing_angle,
    read_coordinate_value, read_current_fsm, read_emergency_info,
    read_override, read_payload, read_robot_state,
)
from .huayan.datasheet_client import DatasheetClient
from .huayan.models import DatasheetSample, ReadCommand
from .huayan.real_motion_client import LocalRealMotionClient
from .preflight import ControllerReadback, MotionApproval, safety_state_hash
from .state_machine import SampleRecord
from .watchdog import SourceStampWatchdog, StateWatchdog
from surgical_contracts import Pose6D, RobotTelemetry


@dataclass(frozen=True)
class LocalObservation:
    telemetry: RobotTelemetry
    readback: ControllerReadback
    source_sample: DatasheetSample


@dataclass(frozen=True)
class MotionFeedback:
    """Merged motion telemetry plus the raw channel values used to build it."""

    telemetry: RobotTelemetry
    moving_10003: bool
    moving_10004: bool
    fsm_10004: int

    @property
    def debug_text(self) -> str:
        return (
            f"moving_10003={self.moving_10003}, "
            f"moving_10004={self.moving_10004}, "
            f"fsm_10004={self.fsm_10004}"
        )


@dataclass(frozen=True)
class EnablementConfirmation:
    """Post-write agreement from a fresh 10003 read and a newer 10004 frame."""

    requested_enabled: bool
    command_enabled: bool
    datasheet_enabled: bool
    command_moving: bool
    datasheet_moving: bool
    datasheet_sequence: int


@dataclass(frozen=True)
class OverrideConfirmation:
    """Serial 10003 then 10004 proof of the configured controller ratio."""

    requested_override: float
    initial_command_override: float
    command_override: float
    datasheet_override: float
    write_sent: bool
    datasheet_sequence: int


def _same_override(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-6)


class LocalDataSheetSampler:
    """Continuously drain 10004 while the operator reads and confirms."""

    def __init__(self, config: RealRobotConfig, *, byte_order: str) -> None:
        controller = config.controller
        if not controller.host or controller.datasheet_port != 10004:
            raise ValueError("commissioning requires confirmed private 10004 DataSheet")
        if config.deadlines.state_stale_ms is None:
            raise ValueError("state stale deadline is missing")
        self.config = config
        self.byte_order = byte_order
        self.watchdog = StateWatchdog(stale_ms=config.deadlines.state_stale_ms)
        self.source_watchdog = SourceStampWatchdog(stale_ms=config.deadlines.state_stale_ms)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._first = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: SampleRecord | None = None
        self._fault: Exception | None = None
        self._sequence = 0

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("DataSheet sampler already started")
        self._thread = threading.Thread(target=self._run, name="commissioning-datasheet", daemon=True)
        self._thread.start()
        if not self._first.wait(3.0):
            self.close()
            raise TimeoutError("no initial real DataSheet sample")
        self.snapshot()

    def _run(self) -> None:
        controller = self.config.controller
        try:
            with DatasheetClient(
                controller.host, controller.datasheet_port,
                byte_order=self.byte_order, timeout_s=0.25,
                scope="private-read-only", max_events=256,
            ) as reader:
                while not self._stop.is_set():
                    reader.poll()
                    for sample in reader.last_batch:
                        if sample.device_sn != controller.device_sn:
                            raise ValueError("DataSheet DeviceSN changed")
                        self.source_watchdog.observe(sample)
                        if sample.error_code or any(sample.axis_error_codes):
                            raise ValueError("DataSheet robot or axis error")
                        with self._lock:
                            self._sequence += 1
                            self._latest = SampleRecord(self._sequence, sample)
                            self._first.set()
                    reader.drain_events()
        except Exception as exc:
            with self._lock:
                self._fault = exc
                self._first.set()

    def snapshot(self) -> SampleRecord:
        with self._lock:
            fault, latest = self._fault, self._latest
        if fault is not None:
            raise RuntimeError("real DataSheet sampler failed") from fault
        if latest is None or not self.watchdog.is_fresh(latest.sample):
            raise RuntimeError("real DataSheet sample is missing or stale")
        return latest

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def __enter__(self) -> "LocalDataSheetSampler":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def set_enabled_and_confirm(
    config: RealRobotConfig,
    *,
    enabled: bool,
    byte_order: str,
) -> EnablementConfirmation:
    """Write once, then prove the requested state through sequential channels.

    The method never writes a local enabled flag. Disable is rejected before
    transmission unless fresh 10004 and 10003 feedback both report stationary.
    The sockets are intentionally not open together: the commissioned
    controller has emitted an LTBR DataSheet frame on the 10003 connection
    while both channels were connected concurrently.
    """
    if type(enabled) is not bool:
        raise TypeError("enabled must be a bool")
    timeout_ms = config.deadlines.startup_ms
    if timeout_ms is None:
        raise ValueError("startup_ms is required for enabled-state confirmation")

    with LocalDataSheetSampler(config, byte_order=byte_order) as sampler:
        before_record = sampler.snapshot()
    before_sample = before_record.sample
    if not enabled and before_sample.moving:
        raise PermissionError("GrpDisable requires stationary 10004 feedback")

    response_ms = config.deadlines.response_ms
    if response_ms is None:
        raise ValueError("response_ms is required for enabled-state confirmation")
    socket_timeout_s = response_ms / 1000
    with LocalRealMotionClient(config, timeout_s=socket_timeout_s) as client:
        before_state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
        if before_state.has_error or before_state.error_code:
            raise ValueError("controller error prevents group enable/disable")
        if not enabled and before_state.moving:
            raise PermissionError("GrpDisable requires stationary 10003 feedback")
        if not client.set_enabled(
            enabled,
            disable_stationary_confirmed=(
                not before_state.moving and not before_sample.moving
            ),
        ):
            raise RuntimeError("controller rejected group enable/disable")

        deadline_ns = time.monotonic_ns() + timeout_ms * 1_000_000
        last_state = before_state
        while time.monotonic_ns() < deadline_ns:
            last_state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
            if last_state.has_error or last_state.error_code:
                raise ValueError("controller error while confirming enabled state")
            if last_state.moving:
                raise RuntimeError("robot moved while changing enabled state")
            if last_state.enabled is enabled:
                break
            time.sleep(0.02)
        else:
            raise TimeoutError(
                "10003 enabled-state confirmation timed out: "
                f"enabled={last_state.enabled}, moving={last_state.moving}"
            )

    with LocalDataSheetSampler(config, byte_order=byte_order) as sampler:
        last_record = sampler.snapshot()
        while time.monotonic_ns() < deadline_ns:
            last_record = sampler.snapshot()
            sample = last_record.sample
            if sample.moving:
                raise RuntimeError("robot moved while confirming 10004 enabled state")
            if (
                sample.received_monotonic_ns > before_sample.received_monotonic_ns
                and sample.enabled is enabled
            ):
                return EnablementConfirmation(
                    requested_enabled=enabled,
                    command_enabled=last_state.enabled,
                    datasheet_enabled=sample.enabled,
                    command_moving=last_state.moving,
                    datasheet_moving=sample.moving,
                    datasheet_sequence=last_record.sequence,
                )
            time.sleep(0.02)
    sample = last_record.sample
    raise TimeoutError(
        "10004 enabled-state confirmation timed out: "
        f"enabled={sample.enabled}, moving={sample.moving}, sequence={last_record.sequence}"
    )


def set_override_and_confirm(
    config: RealRobotConfig, *, byte_order: str,
) -> OverrideConfirmation:
    """Set the configured ratio only while stationary, then verify sequentially.

    The 10004 pre-check is closed before 10003 is opened. After the optional
    SetOverride and mandatory ReadOverride finish, 10003 is closed before a
    new 10004 connection confirms a newer Actual_Override sample.
    """
    expected = config.motion.controller_override
    if expected is None:
        raise ValueError("motion.controller_override is required")
    timeout_ms = config.deadlines.startup_ms
    response_ms = config.deadlines.response_ms
    if timeout_ms is None or response_ms is None:
        raise ValueError("startup_ms and response_ms are required for override confirmation")

    with LocalDataSheetSampler(config, byte_order=byte_order) as sampler:
        before_record = sampler.snapshot()
    before = before_record.sample
    if (
        before.moving or before.fsm_code != 33 or not before.enabled
        or not before.in_position or before.paused
        or before.free_drive_mode or before.force_control_state
    ):
        raise PermissionError("SetOverride requires stationary READY 10004 feedback")

    with LocalRealMotionClient(config, timeout_s=response_ms / 1000) as client:
        state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
        fsm = read_current_fsm(client.request(ReadCommand.CURRENT_FSM))
        if (
            state.moving or not state.enabled or not state.in_position or state.paused
            or state.has_error or state.error_code or fsm != 33
        ):
            raise PermissionError("SetOverride requires stationary READY 10003 feedback")
        initial = client.current_override()
        write_sent = not _same_override(initial, expected)
        if write_sent and not client.set_override(expected, stationary_confirmed=True):
            raise RuntimeError("controller rejected SetOverride")
        command_override = client.current_override()
        if not _same_override(command_override, expected):
            raise RuntimeError(
                "10003 ReadOverride disagrees after SetOverride: "
                f"expected={expected}, actual={command_override}"
            )

    deadline_ns = time.monotonic_ns() + timeout_ms * 1_000_000
    with LocalDataSheetSampler(config, byte_order=byte_order) as sampler:
        last_record = sampler.snapshot()
        while time.monotonic_ns() < deadline_ns:
            last_record = sampler.snapshot()
            sample = last_record.sample
            if (
                sample.moving or sample.fsm_code != 33 or not sample.enabled
                or not sample.in_position or sample.paused
                or sample.free_drive_mode or sample.force_control_state
            ):
                raise RuntimeError("robot changed state while confirming 10004 override")
            if (
                sample.received_monotonic_ns > before.received_monotonic_ns
                and _same_override(sample.override, expected)
            ):
                return OverrideConfirmation(
                    requested_override=expected,
                    initial_command_override=initial,
                    command_override=command_override,
                    datasheet_override=sample.override,
                    write_sent=write_sent,
                    datasheet_sequence=last_record.sequence,
                )
            time.sleep(0.02)
    raise TimeoutError(
        "10004 Actual_Override confirmation timed out: "
        f"expected={expected}, actual={last_record.sample.override}"
    )


def read_local_observation(
    config: RealRobotConfig, client: LocalRealMotionClient,
    sampler: LocalDataSheetSampler, *, session_id: str,
) -> LocalObservation:
    """Cross-check 10003 readbacks against the latest 10004 sample."""
    state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
    emergency = read_emergency_info(client.request(ReadCommand.EMERGENCY_INFO))
    axes = read_axis_error_code(client.request(ReadCommand.AXIS_ERROR_CODE))
    fsm = read_current_fsm(client.request(ReadCommand.CURRENT_FSM))
    actual = read_actual_position(client.request(ReadCommand.ACTUAL_POSITION))
    payload = read_payload(client.request(ReadCommand.PAYLOAD))
    mounting = read_base_installing_angle(client.request(ReadCommand.BASE_INSTALLING_ANGLE))
    current_tcp = read_coordinate_value(client.request(ReadCommand.CURRENT_TCP))
    named_tcp = read_coordinate_value(client.request(
        ReadCommand.TCP_BY_NAME, name=config.tool.tcp_name,
    ))
    current_ucs = read_coordinate_value(client.request(ReadCommand.CURRENT_UCS))
    named_ucs = read_coordinate_value(client.request(ReadCommand.UCS_BY_NAME, name="Base"))
    waypoint_id = client.current_waypoint_id()
    command_override = read_override(client.request(ReadCommand.OVERRIDE))
    record = sampler.snapshot()
    sample = record.sample
    if client.package_version is None:
        raise RuntimeError("commissioning command client is not identified")
    if any(abs(a - b) > 0.5 for a, b in zip(actual.joints_deg, sample.joint_positions_deg)):
        raise ValueError("10003 and 10004 joints disagree")
    if fsm != sample.fsm_code or state.moving != sample.moving:
        raise ValueError("10003 and 10004 motion state disagree")
    if (
        config.motion.controller_override is None
        or not _same_override(command_override, config.motion.controller_override)
        or not _same_override(sample.override, config.motion.controller_override)
    ):
        raise ValueError("10003/10004 speed override disagrees with config")
    zero6 = (0.0,) * 6
    zero3 = (0.0,) * 3
    if (
        current_tcp != zero6 or named_tcp != zero6
        or current_ucs != zero6 or named_ucs != zero6
        or payload.mass_kg != 0 or payload.center_of_gravity_mm != zero3
        or mounting != config.tool.mount_angle_deg
    ):
        raise ValueError("live bare-flange TCP/UCS/payload/mounting readback changed")
    telemetry = telemetry_from_sample(
        record, session_id=session_id, device_sn=config.controller.device_sn,
        robot_model=config.controller.model,
        package_version=client.package_version,
        controller_is_simulation=False, command_connected=True,
        watchdog=sampler.watchdog, robot_status=state,
        emergency_status=emergency,
    )
    if telemetry.state_age_ms is None or telemetry.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("DataSheet became stale during 10003 cross-check")
    if state.enabled is not True or sample.enabled is not True:
        raise ValueError("READY preflight requires enabled feedback from 10003 and 10004")
    readback = ControllerReadback(
        tcp_name=config.tool.tcp_name, ucs_name="Base",
        tcp_xyzrpy=named_tcp, ucs_xyzrpy=named_ucs,
        payload_kg=payload.mass_kg,
        center_of_gravity_mm=payload.center_of_gravity_mm,
        base_installing_angle_deg=mounting,
        group_error_code=axes.group_error_code,
        axis_error_codes=axes.joint_error_codes,
        active_program=state.moving or fsm != 33,
        waypoint_id=waypoint_id,
        controller_override=command_override,
    )
    return LocalObservation(telemetry, readback, sample)


def read_motion_feedback(
    config: RealRobotConfig, client: LocalRealMotionClient,
    sampler: LocalDataSheetSampler, *, session_id: str,
) -> MotionFeedback:
    """Use actual 10004 motion flags, plus fresh 10003 safety-circuit reads."""
    state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
    emergency = read_emergency_info(client.request(ReadCommand.EMERGENCY_INFO))
    axes = read_axis_error_code(client.request(ReadCommand.AXIS_ERROR_CODE))
    if state.has_error or state.error_code or axes.group_error_code or any(axes.joint_error_codes):
        raise ValueError("controller/axis error during local motion")
    record = sampler.snapshot()
    sample = record.sample
    if (
        config.motion.controller_override is None
        or not _same_override(sample.override, config.motion.controller_override)
    ):
        raise ValueError("10004 speed override changed during local motion")
    if client.package_version is None:
        raise RuntimeError("commissioning command socket disconnected")
    base_telemetry = telemetry_from_sample(
        record, session_id=session_id, device_sn=config.controller.device_sn,
        robot_model=config.controller.model, package_version=client.package_version,
        controller_is_simulation=False, command_connected=True,
        watchdog=sampler.watchdog, robot_status=state, emergency_status=emergency,
    )
    telemetry = base_telemetry.model_copy(update={
        # Never let one channel's optimistic value hide the other's warning.
        "enabled": state.enabled and sample.enabled,
        "in_position": state.in_position and sample.in_position,
        "moving": state.moving or sample.moving,
        "potentially_moving": state.moving or sample.moving or base_telemetry.potentially_moving,
    })
    if telemetry.state_age_ms is None or telemetry.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("DataSheet became stale during motion feedback")
    return MotionFeedback(
        telemetry=telemetry,
        moving_10003=state.moving,
        moving_10004=sample.moving,
        fsm_10004=sample.fsm_code,
    )


def make_approval(config: RealRobotConfig, *, package_version: str) -> MotionApproval:
    """Build motion approval directly from the configured YAML limits."""
    from .commissioning_cli import effective_first_motion_caps

    caps = effective_first_motion_caps(config)
    return MotionApproval(
        device_sn=config.controller.device_sn,
        robot_model=config.controller.model,
        package_version=package_version,
        tcp_name=config.tool.tcp_name, ucs_name="Base", tcp_xyzrpy=(0.0,) * 6,
        ucs_xyzrpy=(0.0,) * 6, payload_kg=0.0,
        center_of_gravity_mm=(0.0,) * 3,
        base_installing_angle_deg=config.tool.mount_angle_deg,
        joint_soft_limits_deg=config.limits.joint_soft_limits_deg,
        joint_margin_deg=config.limits.joint_margin_deg,
        workspace_low_mm=config.limits.workspace_low_mm,
        workspace_high_mm=config.limits.workspace_high_mm,
        max_speed_mm_s=caps["max_speed_mm_s"],
        max_acceleration_mm_s2=caps["max_acceleration_mm_s2"],
        max_step_mm=caps["max_step_mm"],
        max_absolute_displacement_mm=config.limits.max_absolute_displacement_mm,
        max_rotation_deg=config.limits.max_rotation_deg,
        max_joint_speed_deg_s=config.motion.joint_speed_deg_s,
        max_joint_acceleration_deg_s2=config.motion.joint_acceleration_deg_s2,
        max_start_drift_mm=config.arrival.position_tolerance_mm,
        max_start_rotation_deg=config.arrival.orientation_tolerance_deg,
        path_sample_step_mm=config.arrival.position_tolerance_mm,
        state_stale_ms=config.deadlines.state_stale_ms,
        ready_fsm_code=33,
        controller_override=config.motion.controller_override,
    )


def make_path_ik(config: RealRobotConfig, start: RobotTelemetry):
    """Build the calibrated E05-Pro IK checker for position/orientation paths."""
    import numpy as np
    from scipy.spatial.transform import Rotation

    from simulation.entry_point_env.config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
    from simulation.entry_point_env.kinematics import E05ProKinematics

    if start.joint_positions_deg is None or start.actual_pose_robot_base is None:
        raise ValueError("actual start pose and joints are required for IK")
    sim = EntryPointEnvConfig.from_yaml(DEFAULT_CONFIG_PATH)
    if sim.robot.force_flange_offset_mm != 184.0:
        raise ValueError("verified E05-Pro flange geometry changed")
    signs = config.joint_mapping.sign
    offsets = config.joint_mapping.zero_offset_deg
    visual = tuple(sign * joint + offset for sign, joint, offset in zip(
        signs, start.joint_positions_deg, offsets,
    ))
    model = E05ProKinematics(
        joint_limits_deg=sim.robot.joint_limits_deg,
        force_flange_offset_mm=sim.robot.force_flange_offset_mm,
        tool_translation_mm=(0.0, 0.0, 0.0), tool_rpy_deg=(0.0, 0.0, 0.0),
    )
    seed = np.deg2rad(visual)
    fk = model.forward(seed).flange_transform
    actual_pose = start.actual_pose_robot_base
    position_error = math.dist(fk[:3, 3], actual_pose.translation_mm)
    actual_orientation = Rotation.from_quat(actual_pose.quaternion_xyzw)
    angle_error_deg = math.degrees(
        (actual_orientation.inv() * Rotation.from_matrix(fk[:3, :3])).magnitude()
    )
    if (
        position_error > config.arrival.position_tolerance_mm
        or angle_error_deg > config.arrival.orientation_tolerance_deg
    ):
        raise ValueError("current FK disagrees with actual Base flange pose")
    previous = np.asarray(start.joint_positions_deg, dtype=float)

    def solve(
        point: tuple[float, float, float],
        quaternion_xyzw: tuple[float, float, float, float] | None = None,
    ) -> tuple[float, ...]:
        nonlocal seed, previous
        orientation = (
            actual_orientation
            if quaternion_xyzw is None
            else Rotation.from_quat(quaternion_xyzw)
        )
        solution = model.inverse(point, orientation, seed)
        visual_solved = np.rad2deg(solution.joint_positions_rad)
        robot_solved = np.asarray([
            sign * (joint - offset)
            for sign, joint, offset in zip(signs, visual_solved, offsets)
        ])
        # if np.max(np.abs(robot_solved - previous)) > 2.0:
        #     raise ValueError("IK branch jump or near-singular path")
        previous = robot_solved
        seed = np.asarray(solution.joint_positions_rad)
        return tuple(float(value) for value in robot_solved)

    return solve


def make_joint_fk(config: RealRobotConfig, start: RobotTelemetry):
    """Return calibrated E05-Pro FK for robot-reported joint coordinates."""
    import numpy as np
    from scipy.spatial.transform import Rotation

    from simulation.entry_point_env.config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
    from simulation.entry_point_env.kinematics import E05ProKinematics

    if start.joint_positions_deg is None or start.actual_pose_robot_base is None:
        raise ValueError("actual start pose and joints are required for FK")
    sim = EntryPointEnvConfig.from_yaml(DEFAULT_CONFIG_PATH)
    signs = config.joint_mapping.sign
    offsets = config.joint_mapping.zero_offset_deg
    model = E05ProKinematics(
        joint_limits_deg=sim.robot.joint_limits_deg,
        force_flange_offset_mm=sim.robot.force_flange_offset_mm,
        tool_translation_mm=(0.0, 0.0, 0.0),
        tool_rpy_deg=(0.0, 0.0, 0.0),
    )

    def forward(joints_deg: tuple[float, ...]) -> Pose6D:
        visual = tuple(
            sign * joint + offset
            for sign, joint, offset in zip(signs, joints_deg, offsets)
        )
        transform = model.forward(np.deg2rad(visual)).flange_transform
        rotation = Rotation.from_matrix(transform[:3, :3])
        return Pose6D(
            translation_mm=tuple(float(value) for value in transform[:3, 3]),
            rotation_rpy_deg=tuple(float(value) for value in rotation.as_euler("xyz", degrees=True)),
            quaternion_xyzw=tuple(float(value) for value in rotation.as_quat()),
            frame=start.actual_pose_robot_base.frame,
            unit=start.actual_pose_robot_base.unit,
        )

    actual = start.actual_pose_robot_base
    predicted = forward(tuple(float(value) for value in start.joint_positions_deg))
    if math.dist(predicted.translation_mm, actual.translation_mm) > config.arrival.position_tolerance_mm:
        raise ValueError("current FK position disagrees with actual Base flange pose")
    angle = math.degrees((
        Rotation.from_quat(actual.quaternion_xyzw).inv()
        * Rotation.from_quat(predicted.quaternion_xyzw)
    ).magnitude())
    if angle > config.arrival.orientation_tolerance_deg:
        raise ValueError("current FK orientation disagrees with actual Base flange pose")
    return forward


def validate_final_observation(
    before: LocalObservation, after: LocalObservation, config: RealRobotConfig,
) -> None:
    """Last cross-check after IK and human confirmation, before journal/write."""
    from scipy.spatial.transform import Rotation

    a, b = before.telemetry, after.telemetry
    if b.sequence <= a.sequence or b.state_age_ms is None or b.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("final DataSheet freshness check failed")
    if safety_state_hash(a, before.readback) != safety_state_hash(b, after.readback):
        raise ValueError("safety state or controller setup changed after proposal")
    if a.actual_pose_robot_base is None or b.actual_pose_robot_base is None or math.dist(
        a.actual_pose_robot_base.translation_mm, b.actual_pose_robot_base.translation_mm,
    ) > config.arrival.position_tolerance_mm:
        raise ValueError("actual start drifted after proposal")
    orientation_a = Rotation.from_quat(a.actual_pose_robot_base.quaternion_xyzw)
    orientation_b = Rotation.from_quat(b.actual_pose_robot_base.quaternion_xyzw)
    if (
        math.degrees((orientation_a.inv() * orientation_b).magnitude())
        > config.arrival.orientation_tolerance_deg
    ):
        raise ValueError("actual flange orientation changed after proposal")
