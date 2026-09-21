"""One-shot, fail-closed read-only probe for Step 6 commissioning.

Importing this module and ``--check-config`` never open a controller socket.
The live CLI requires explicit operator and vendor-compatibility flags.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import struct
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from .adapter import (
    read_actual_position, read_axis_error_code, read_base_installing_angle,
    read_controller_started, read_coordinate_value, read_current_fsm,
    read_emergency_info, read_fast_port, read_identity_text, read_is_simulation,
    read_payload, read_robot_state,
)
from .command_client import CommandClient, _private_controller_host
from .command_codec import validate_identifier
from .datasheet_codec import HEADER_BYTES, MAGIC, MAX_FRAME_BYTES, parse_datasheet
from .models import ProtocolError, ReadCommand
from robot_runtime.real_config import RealRobotConfig, load_real_config


@dataclass(frozen=True)
class ProbeResult:
    summary: dict[str, object]
    raw_datasheet_frame: bytes


def validate_probe_config(config: RealRobotConfig) -> None:
    controller = config.controller
    if config.allowed_control != "observe-only":
        raise ValueError("real config must remain observe-only")
    if not controller.host:
        raise ValueError("controller.host must be confirmed from the vendor page")
    _private_controller_host(controller.host)
    if controller.command_port != 10003 or controller.datasheet_port != 10004:
        raise ValueError("first read-only probe requires confirmed ports 10003 and 10004")
    if not controller.device_sn or not controller.asset_id or not controller.model or not controller.package_versions:
        raise ValueError("asset ID, DeviceSN, model and allowed PackageVersion must be confirmed first")
    if config.deadlines.state_stale_ms is None or not 50 <= config.deadlines.state_stale_ms < 1500:
        raise ValueError("state_stale_ms must be 50..1499 for the read-only gateway")


def _recv_exact(connection: socket.socket, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise ConnectionError("DataSheet stream closed before one complete frame")
        result.extend(chunk)
    return bytes(result)


def read_one_datasheet_frame(
    host: str, port: int, *, byte_order: Literal["little", "big"],
) -> bytes:
    if byte_order not in ("little", "big"):
        raise ValueError("DataSheet byte order must be selected explicitly")
    with socket.create_connection((host, port), timeout=2.0) as connection:
        connection.settimeout(2.0)
        header = _recv_exact(connection, HEADER_BYTES)
        if header[:4] != MAGIC:
            raise ProtocolError("DataSheet did not start with LTBR magic")
        total, json_length = struct.unpack(
            "<II" if byte_order == "little" else ">II", header[4:],
        )
        if not HEADER_BYTES + 2 <= total <= MAX_FRAME_BYTES or json_length != total - HEADER_BYTES:
            raise ProtocolError("DataSheet length or selected byte order is wrong")
        return header + _recv_exact(connection, json_length)


def validate_no_tool_probe_summary(summary: dict[str, object], config: RealRobotConfig) -> None:
    """Check the recorded read-only controller values for a no-tool profile.

    This proves value agreement, not that the flange is physically bare or
    that Gate C / a particular motion has been authorized.
    """
    if config.tool.setup != "flange_only_no_tool":
        return

    def matches(value: object, expected: tuple[float, ...]) -> bool:
        return (
            isinstance(value, (list, tuple)) and len(value) == len(expected)
            and all(
                type(actual) in (int, float) and math.isfinite(actual)
                and abs(actual - wanted) <= 1e-6
                for actual, wanted in zip(value, expected)
            )
        )

    payload = summary.get("payload")
    expected_zero6 = (0.0,) * 6
    expected_zero3 = (0.0,) * 3
    if (
        summary.get("approved_tcp_name") != config.tool.tcp_name
        or summary.get("approved_ucs_name") != "Base"
        or not matches(summary.get("current_tcp"), expected_zero6)
        or not matches(summary.get("approved_tcp_value"), expected_zero6)
        or not matches(summary.get("current_ucs"), expected_zero6)
        or not matches(summary.get("approved_ucs_value"), expected_zero6)
        or not isinstance(payload, dict)
        or type(payload.get("mass_kg")) not in (int, float)
        or not math.isfinite(payload["mass_kg"])
        or abs(payload["mass_kg"]) > 1e-6
        or not matches(payload.get("center_of_gravity_mm"), expected_zero3)
        or config.tool.mount_angle_deg is None
        or not matches(summary.get("base_installing_angle_deg"), config.tool.mount_angle_deg)
    ):
        raise ValueError("no-tool TCP/UCS/payload/installing-angle readback disagrees with real config")


def probe_once(
    config: RealRobotConfig,
    *,
    byte_order: Literal["little", "big"],
    scope: Literal["loopback", "private-read-only"] = "loopback",
    approved_tcp_name: str | None = None,
    approved_ucs_name: str | None = None,
) -> ProbeResult:
    """Run the fixed read-only sequence once; never retry a lost reply."""
    if scope == "private-read-only":
        validate_probe_config(config)
    elif scope != "loopback":
        raise ValueError("invalid probe connection scope")
    controller = config.controller
    if not controller.host or not controller.command_port or not controller.datasheet_port:
        raise ValueError("controller connection settings are incomplete")
    if approved_tcp_name is not None:
        validate_identifier(approved_tcp_name)
    if approved_ucs_name is not None:
        validate_identifier(approved_ucs_name)
    if config.tool.setup == "flange_only_no_tool":
        if approved_tcp_name is not None and approved_tcp_name != config.tool.tcp_name:
            raise ValueError("approved TCP name disagrees with no-tool real config")
        if approved_ucs_name is not None and approved_ucs_name != "Base":
            raise ValueError("approved UCS name must be Base for no-tool real config")
        approved_tcp_name = config.tool.tcp_name
        approved_ucs_name = "Base"

    with CommandClient(
        controller.host, controller.command_port, timeout_s=2.0, scope=scope,
    ) as command:
        version = read_identity_text(command.request(ReadCommand.PACKAGE_VERSION))
        if version not in controller.package_versions:
            raise ValueError("PackageVersion does not match the approved real config")
        model = read_identity_text(command.request(ReadCommand.ROBOT_MODEL))
        if model != controller.model:
            raise ValueError("robot model does not match the approved real config")
        if read_is_simulation(command.request(ReadCommand.IS_SIMULATION)):
            raise ValueError("controller reports simulation mode")
        if not read_controller_started(command.request(ReadCommand.CONTROLLER_STATE)):
            raise ValueError("controller is not in the expected started state")
        fast_port = read_fast_port(command.request(ReadCommand.FAST_COMMAND_PORT))
        robot_state = read_robot_state(command.request(ReadCommand.ROBOT_STATE))
        if (
            robot_state.moving or robot_state.has_error or robot_state.emergency_stop
            or robot_state.safeguard or not robot_state.controller_box_connected
        ):
            raise ValueError("robot or safety status is abnormal; stop commissioning")
        fsm = read_current_fsm(command.request(ReadCommand.CURRENT_FSM))
        actual = read_actual_position(command.request(ReadCommand.ACTUAL_POSITION))
        axis_error = read_axis_error_code(command.request(ReadCommand.AXIS_ERROR_CODE))
        emergency = read_emergency_info(command.request(ReadCommand.EMERGENCY_INFO))
        if (
            emergency.emergency_circuit_fault or emergency.safeguard_circuit_fault
            or emergency.emergency_stop or emergency.safeguard
        ):
            raise ValueError("emergency or safeguard status is abnormal; stop commissioning")
        payload = read_payload(command.request(ReadCommand.PAYLOAD))
        base_angles = read_base_installing_angle(command.request(ReadCommand.BASE_INSTALLING_ANGLE))
        current_tcp = read_coordinate_value(command.request(ReadCommand.CURRENT_TCP))
        current_ucs = read_coordinate_value(command.request(ReadCommand.CURRENT_UCS))
        named_tcp = (
            read_coordinate_value(command.request(ReadCommand.TCP_BY_NAME, name=approved_tcp_name))
            if approved_tcp_name else None
        )
        named_ucs = (
            read_coordinate_value(command.request(ReadCommand.UCS_BY_NAME, name=approved_ucs_name))
            if approved_ucs_name else None
        )

    raw_frame = read_one_datasheet_frame(
        controller.host, controller.datasheet_port, byte_order=byte_order,
    )
    sample = parse_datasheet(
        raw_frame[HEADER_BYTES:],
        received_wall_ms=time.time_ns() // 1_000_000,
        received_monotonic_ns=time.monotonic_ns(),
    )
    if not sample.device_sn or sample.device_sn != controller.device_sn:
        raise ValueError("DataSheet DeviceSN does not match the approved real config")
    if sample.moving or sample.error_code or any(sample.axis_error_codes):
        raise ValueError("DataSheet reports moving or error state; stop commissioning")
    if any(abs(a - b) > 0.5 for a, b in zip(actual.joints_deg, sample.joint_positions_deg)):
        raise ValueError("command and DataSheet joint positions disagree by more than 0.5 degrees")
    summary: dict[str, object] = {
        "captured_at_ms": time.time_ns() // 1_000_000,
        "control_mode": "observe-only",
        "config_sha256": config.digest(),
        "device_sn": sample.device_sn,
        "robot_model": model,
        "package_version": version,
        "fast_command_port_reported": fast_port,
        "datasheet_byte_order": byte_order,
        "datasheet_frame_bytes": len(raw_frame),
        "datasheet_source_timestamp_ms": sample.source_timestamp_ms,
        "joint_positions_deg": sample.joint_positions_deg,
        "actual_position_joints_deg": actual.joints_deg,
        "base_pose": sample.base_pose,
        "fsm_command": fsm,
        "fsm_datasheet": sample.fsm_code,
        "moving": sample.moving,
        "error_code": sample.error_code,
        "axis_error_codes": sample.axis_error_codes,
        "enabled": sample.enabled,
        "in_position": sample.in_position,
        "robot_state": vars(robot_state),
        "axis_error": vars(axis_error),
        "emergency_info": vars(emergency),
        "payload": vars(payload),
        "base_installing_angle_deg": base_angles,
        "current_tcp": current_tcp,
        "current_ucs": current_ucs,
        "approved_tcp_name": approved_tcp_name,
        "approved_tcp_value": named_tcp,
        "approved_ucs_name": approved_ucs_name,
        "approved_ucs_value": named_ucs,
    }
    validate_no_tool_probe_summary(summary, config)
    if config.tool.setup == "flange_only_no_tool":
        summary["no_tool_readback_verified"] = True
    return ProbeResult(summary, raw_frame)


def validate_probe_summary(
    path: Path, config: RealRobotConfig, *, byte_order: Literal["little", "big"],
) -> None:
    """Require a recent successful local probe before continuous real streaming."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("probe summary must be a regular, bounded local file")
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("probe summary is not valid JSON") from exc
    if not isinstance(summary, dict):
        raise ValueError("probe summary must be an object")
    captured_at = summary.get("captured_at_ms")
    now_ms = time.time_ns() // 1_000_000
    if type(captured_at) is not int or not 0 <= now_ms - captured_at <= 60 * 60 * 1000:
        raise ValueError("probe summary is older than one hour or has a future timestamp")
    if (
        summary.get("control_mode") != "observe-only"
        or summary.get("config_sha256") != config.digest()
        or summary.get("device_sn") != config.controller.device_sn
        or summary.get("robot_model") != config.controller.model
        or summary.get("package_version") not in config.controller.package_versions
        or summary.get("datasheet_byte_order") != byte_order
        or summary.get("moving") is not False
        or summary.get("error_code") != 0
        or summary.get("axis_error_codes") != [0, 0, 0, 0, 0, 0]
    ):
        raise ValueError("probe summary disagrees with real gateway configuration")
    state = summary.get("robot_state")
    emergency = summary.get("emergency_info")
    if (
        not isinstance(state, dict) or state.get("moving") is not False
        or not isinstance(emergency, dict)
        or emergency.get("emergency_circuit_fault") is not False
        or emergency.get("safeguard_circuit_fault") is not False
        or emergency.get("emergency_stop") is not False
        or emergency.get("safeguard") is not False
    ):
        raise ValueError("probe summary has an unsafe or incomplete state")
    validate_no_tool_probe_summary(summary, config)


def _save_probe_result(result: ProbeResult) -> Path:
    app_root = Path(__file__).resolve().parents[2]
    output_dir = (
        app_root / "artifacts" / "real_robot_commissioning" / date.today().isoformat()
        / "step6" / f"probe-{time.time_ns()}-{os.getpid()}"
    )
    previous_umask = os.umask(0o077)
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "read-only-summary.json").write_text(
            json.dumps(result.summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        (output_dir / "datasheet-first-frame.bin").write_bytes(result.raw_datasheet_frame)
    finally:
        os.umask(previous_umask)
    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 6 one-shot real read-only controller probe")
    parser.add_argument("--real-config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check-config", action="store_true", help="validate only; no network")
    action.add_argument("--connect-real-read-only", action="store_true", help="send only the fixed read commands")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--operator-ready", action="store_true", help="stationary robot and safety checks completed")
    parser.add_argument("--byte-order", choices=("little", "big"))
    parser.add_argument("--approved-tcp-name")
    parser.add_argument("--approved-ucs-name")
    args = parser.parse_args()
    config = load_real_config(args.real_config)
    validate_probe_config(config)
    if args.check_config:
        print("READ-ONLY CONFIG OK; no controller connection was opened")
        return 0
    if not args.vendor_compatibility_confirmed or not args.operator_ready or not args.byte_order:
        parser.error("real connection requires vendor compatibility, operator readiness and explicit byte order")
    result = probe_once(
        config,
        byte_order=args.byte_order,
        scope="private-read-only",
        approved_tcp_name=args.approved_tcp_name,
        approved_ucs_name=args.approved_ucs_name,
    )
    saved = _save_probe_result(result)
    print(f"READ-ONLY PROBE OK; raw local record: {saved}")
    print("No motion, reset, enable, IO write or script command was sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
