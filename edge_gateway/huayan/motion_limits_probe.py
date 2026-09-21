"""One-shot, read-only inspection of controller motion maxima.

These values describe controller settings, not approved project motion caps.
No motion, configuration-write, or safety-setting command is available here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal

from robot_runtime.real_config import RealRobotConfig, load_real_config

from .adapter import (
    read_identity_text, read_is_simulation, read_joint_max_acceleration,
    read_joint_max_velocity, read_linear_max_motion,
)
from .command_client import CommandClient
from .command_codec import encode_read
from .models import ReadCommand
from .real_probe import probe_once, validate_probe_config


MOTION_LIMIT_READS = (
    ReadCommand.JOINT_MAX_VELOCITY,
    ReadCommand.JOINT_MAX_ACCELERATION,
    ReadCommand.LINEAR_MAX_MOTION,
)


def read_motion_limits(
    config: RealRobotConfig, *, byte_order: Literal["little", "big"],
    scope: Literal["loopback", "private-read-only"] = "loopback",
) -> dict[str, object]:
    """Check identity and static state first, then read three documented maxima."""
    if scope == "private-read-only":
        validate_probe_config(config)
    elif scope != "loopback":
        raise ValueError("invalid probe connection scope")
    initial = probe_once(config, byte_order=byte_order, scope=scope)
    controller = config.controller
    if controller.host is None or controller.command_port is None:
        raise ValueError("controller connection settings are incomplete")

    with CommandClient(
        controller.host, controller.command_port, timeout_s=2.0, scope=scope,
    ) as command:
        # A fresh socket must not inherit an unchecked identity from the probe.
        version = read_identity_text(command.request(ReadCommand.PACKAGE_VERSION))
        if version not in controller.package_versions:
            raise ValueError("controller identity changed after the read-only probe")
        model = read_identity_text(command.request(ReadCommand.ROBOT_MODEL))
        if model != controller.model:
            raise ValueError("controller identity changed after the read-only probe")
        simulation = read_is_simulation(command.request(ReadCommand.IS_SIMULATION))
        if simulation:
            raise ValueError("controller identity changed after the read-only probe")
        joint_velocity = read_joint_max_velocity(command.request(ReadCommand.JOINT_MAX_VELOCITY))
        joint_acceleration = read_joint_max_acceleration(command.request(ReadCommand.JOINT_MAX_ACCELERATION))
        linear = read_linear_max_motion(command.request(ReadCommand.LINEAR_MAX_MOTION))

    return {
        "control_mode": "observe-only",
        "captured_at_ms": initial.summary["captured_at_ms"],
        "config_sha256": initial.summary["config_sha256"],
        "device_sn": initial.summary["device_sn"],
        "robot_model": model,
        "package_version": version,
        "joint_max_velocity_deg_s": joint_velocity,
        "joint_max_acceleration_deg_s2": joint_acceleration,
        "linear_max_velocity_mm_s": linear.velocity_mm_s,
        "linear_max_acceleration_mm_s2": linear.acceleration_mm_s2,
        "linear_max_jerk_mm_s3": linear.jerk_mm_s3,
        "note": "Controller-configured maxima only; not approved project speed/acceleration caps.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only inspection of HansRobot controller motion maxima")
    parser.add_argument("--real-config", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--show-requests", action="store_true", help="print the additional maxima reads; no network")
    action.add_argument("--check-config", action="store_true", help="validate only; no network")
    action.add_argument("--connect-real-read-only", action="store_true")
    parser.add_argument("--byte-order", choices=("little", "big"))
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--operator-ready", action="store_true", help="robot stationary and local safety checks completed")
    args = parser.parse_args()

    config = load_real_config(args.real_config)
    validate_probe_config(config)
    if args.show_requests:
        print("Live mode first runs the existing Step 6 read-only safety/identity probe, then sends:")
        for command in MOTION_LIMIT_READS:
            print(encode_read(command).decode("ascii"))
        print("No network connection was opened")
        return 0
    if args.check_config:
        print("READ-ONLY CONFIG OK; no controller connection was opened")
        return 0
    if not args.vendor_compatibility_confirmed or not args.operator_ready or not args.byte_order:
        parser.error("real connection requires vendor compatibility, operator readiness and explicit byte order")
    result = read_motion_limits(config, byte_order=args.byte_order, scope="private-read-only")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
