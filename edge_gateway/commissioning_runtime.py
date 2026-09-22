"""Mac-local feedback and Gate D inputs for one bare-flange 1 mm trial.

No cloud transport is imported here. This module does not contain a loop or
entry point that sends motion; commissioning_cli owns each human confirmation.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

import numpy as np
from scipy.spatial.transform import Rotation

from robot_runtime.real_config import RealRobotConfig
from simulation.entry_point_env.config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
from simulation.entry_point_env.kinematics import E05ProKinematics

from .cloud_transport import telemetry_from_sample
from .huayan.adapter import (
    fixed_xyz_quaternion, read_actual_position, read_axis_error_code, read_base_installing_angle,
    read_coordinate_value, read_current_fsm, read_emergency_info,
    read_payload, read_robot_state,
)
from .huayan.datasheet_client import DatasheetClient
from .huayan.models import DatasheetSample, ReadCommand
from .huayan.real_motion_client import LocalRealMotionClient
from .preflight import ControllerReadback, MotionApproval, safety_state_hash
from .state_machine import SampleRecord
from .watchdog import SourceStampWatchdog, StateWatchdog
from surgical_contracts import Pose6D, RobotTelemetry


STATIONARY_OBSERVATION_S = 5.0


@dataclass(frozen=True)
class LocalObservation:
    telemetry: RobotTelemetry
    readback: ControllerReadback
    source_sample: DatasheetSample


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
    record = sampler.snapshot()
    sample = record.sample
    if client.package_version is None:
        raise RuntimeError("commissioning command client is not identified")
    if any(abs(a - b) > 0.5 for a, b in zip(actual.joints_deg, sample.joint_positions_deg)):
        raise ValueError("10003 and 10004 joints disagree")
    if fsm != sample.fsm_code or state.moving != sample.moving:
        raise ValueError("10003 and 10004 motion state disagree")
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
    ).model_copy(update={"control_mode": "enabled"})
    if telemetry.state_age_ms is None or telemetry.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("DataSheet became stale during 10003 cross-check")
    if sample.enabled is not True or not all(sample.brake_states):
        raise ValueError("DataSheet reports disabled robot or held brake")
    readback = ControllerReadback(
        config_sha256=config.digest(), tcp_name=config.tool.tcp_name,
        ucs_name="Base", tcp_xyzrpy=named_tcp, ucs_xyzrpy=named_ucs,
        payload_kg=payload.mass_kg,
        center_of_gravity_mm=payload.center_of_gravity_mm,
        base_installing_angle_deg=mounting,
        group_error_code=axes.group_error_code,
        axis_error_codes=axes.joint_error_codes,
        active_program=state.moving or fsm != 33,
        waypoint_id=waypoint_id,
    )
    return LocalObservation(telemetry, readback, sample)


def read_motion_feedback(
    config: RealRobotConfig, client: LocalRealMotionClient,
    sampler: LocalDataSheetSampler, *, session_id: str,
) -> RobotTelemetry:
    """Use actual 10004 motion flags, plus fresh 10003 safety-circuit reads."""
    state = read_robot_state(client.request(ReadCommand.ROBOT_STATE))
    emergency = read_emergency_info(client.request(ReadCommand.EMERGENCY_INFO))
    axes = read_axis_error_code(client.request(ReadCommand.AXIS_ERROR_CODE))
    if state.has_error or state.error_code or axes.group_error_code or any(axes.joint_error_codes):
        raise ValueError("controller/axis error during local motion")
    record = sampler.snapshot()
    sample = record.sample
    if client.package_version is None:
        raise RuntimeError("commissioning command socket disconnected")
    base_telemetry = telemetry_from_sample(
        record, session_id=session_id, device_sn=config.controller.device_sn,
        robot_model=config.controller.model, package_version=client.package_version,
        controller_is_simulation=False, command_connected=True,
        watchdog=sampler.watchdog, robot_status=state, emergency_status=emergency,
    )
    telemetry = base_telemetry.model_copy(update={
        "control_mode": "enabled",
        # Never let one channel's optimistic value hide the other's warning.
        "enabled": state.enabled and sample.enabled,
        "brakes_released": state.brakes_released and all(sample.brake_states),
        "in_position": state.in_position and sample.in_position,
        "moving": state.moving or sample.moving,
        "potentially_moving": state.moving or sample.moving or base_telemetry.potentially_moving,
    })
    if telemetry.state_age_ms is None or telemetry.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("DataSheet became stale during motion feedback")
    return telemetry


def observe_stationary(
    sampler: LocalDataSheetSampler, *, duration_s: float = STATIONARY_OBSERVATION_S,
    poll_s: float = 0.05,
) -> None:
    """Short pre-motion stationary observation; any unexpected motion aborts."""
    initial = sampler.snapshot().sample
    start_pose = initial.base_pose[:3]
    start_joints = initial.joint_positions_deg
    start_orientation = Rotation.from_quat(fixed_xyz_quaternion(initial.base_pose[3:6]))
    mode = (initial.auto_mode, initial.reduced_mode)
    if (
        initial.moving or initial.fsm_code != 33 or not initial.enabled
        or not initial.in_position or not all(initial.brake_states)
        or initial.free_drive_mode or initial.force_control_state or initial.paused
    ):
        raise ValueError("robot is not stationary, enabled and READY")
    end_ns = time.monotonic_ns() + int(duration_s * 1_000_000_000)
    while time.monotonic_ns() < end_ns:
        sample = sampler.snapshot().sample
        if (
            sample.moving or sample.fsm_code != 33 or not sample.enabled
            or not sample.in_position or sample.paused
            or not all(sample.brake_states) or sample.free_drive_mode or sample.force_control_state
            or (sample.auto_mode, sample.reduced_mode) != mode
            or math.dist(sample.base_pose[:3], start_pose) > 0.25
            or max(abs(a - b) for a, b in zip(sample.joint_positions_deg, start_joints)) > 0.1
            or math.degrees((
                start_orientation.inv()
                * Rotation.from_quat(fixed_xyz_quaternion(sample.base_pose[3:6]))
            ).magnitude()) > 0.1
        ):
            raise ValueError("robot moved or changed safety mode during observation")
        time.sleep(poll_s)


def make_approval(config: RealRobotConfig, *, package_version: str) -> MotionApproval:
    """Apply lower local trial caps without changing controller readback YAML."""
    from .commissioning_cli import effective_first_motion_caps

    caps = effective_first_motion_caps(config)
    return MotionApproval(
        device_sn=config.controller.device_sn,
        robot_model=config.controller.model,
        package_version=package_version,
        config_sha256=config.digest(), tcp_name=config.tool.tcp_name,
        ucs_name="Base", tcp_xyzrpy=(0.0,) * 6,
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
        max_start_drift_mm=0.25, max_start_rotation_deg=0.5,
        state_stale_ms=config.deadlines.state_stale_ms,
        ready_fsm_code=33,
    )


def make_path_ik(config: RealRobotConfig, start: RobotTelemetry):
    """Use the Step 8 calibrated E05-Pro model for every 0.1 mm path sample."""
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
    orientation = Rotation.from_quat(actual_pose.quaternion_xyzw)
    angle_error_deg = math.degrees((orientation.inv() * Rotation.from_matrix(fk[:3, :3])).magnitude())
    if position_error > 0.5 or angle_error_deg > 0.5:
        raise ValueError("current FK disagrees with actual Base flange pose")
    previous = np.asarray(start.joint_positions_deg, dtype=float)

    def solve(point: tuple[float, float, float]) -> tuple[float, ...]:
        nonlocal seed, previous
        solution = model.inverse(point, orientation, seed)
        visual_solved = np.rad2deg(solution.joint_positions_rad)
        robot_solved = np.asarray([
            sign * (joint - offset)
            for sign, joint, offset in zip(signs, visual_solved, offsets)
        ])
        if np.max(np.abs(robot_solved - previous)) > 2.0:
            raise ValueError("IK branch jump or near-singular path")
        previous = robot_solved
        seed = np.asarray(solution.joint_positions_rad)
        return tuple(float(value) for value in robot_solved)

    return solve


def validate_final_observation(
    before: LocalObservation, after: LocalObservation, config: RealRobotConfig,
) -> None:
    """Last cross-check after IK and human confirmation, before journal/write."""
    a, b = before.telemetry, after.telemetry
    if b.sequence <= a.sequence or b.state_age_ms is None or b.state_age_ms > config.deadlines.state_stale_ms:
        raise ValueError("final DataSheet freshness check failed")
    if safety_state_hash(a, before.readback) != safety_state_hash(b, after.readback):
        raise ValueError("safety state or controller setup changed after proposal")
    if a.actual_pose_robot_base is None or b.actual_pose_robot_base is None or math.dist(
        a.actual_pose_robot_base.translation_mm, b.actual_pose_robot_base.translation_mm,
    ) > 0.25:
        raise ValueError("actual start drifted after proposal")
    if (
        a.joint_positions_deg is None or b.joint_positions_deg is None
        or max(abs(x - y) for x, y in zip(a.joint_positions_deg, b.joint_positions_deg)) > 0.1
    ):
        raise ValueError("actual joints changed after proposal")
    orientation_a = Rotation.from_quat(a.actual_pose_robot_base.quaternion_xyzw)
    orientation_b = Rotation.from_quat(b.actual_pose_robot_base.quaternion_xyzw)
    if math.degrees((orientation_a.inv() * orientation_b).magnitude()) > 0.1:
        raise ValueError("actual flange orientation changed after proposal")
