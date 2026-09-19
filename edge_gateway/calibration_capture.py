"""Capture one stationary Step 8 sample from receive-only DataSheet feedback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robot_runtime.real_config import load_real_config

from .huayan.adapter import fixed_xyz_quaternion
from .huayan.datasheet_client import DatasheetClient


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture one stationary, receive-only calibration sample"
    )
    parser.add_argument("--real-config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--split", choices=("fit", "validation"), required=True)
    parser.add_argument("--visual-joints-deg", type=float, nargs=6, required=True)
    parser.add_argument("--sofa-world-point-mm", type=float, nargs=3, required=True)
    parser.add_argument(
        "--sofa-world-quaternion-xyzw", type=float, nargs=4, required=True
    )
    parser.add_argument("--byte-order", choices=("little", "big"), required=True)
    parser.add_argument("--connect-real-read-only", action="store_true")
    parser.add_argument("--vendor-compatibility-confirmed", action="store_true")
    parser.add_argument("--operator-ready", action="store_true")
    arguments = parser.parse_args()
    if not (
        arguments.connect_real_read_only
        and arguments.vendor_compatibility_confirmed
        and arguments.operator_ready
    ):
        parser.error("capture requires all three explicit read-only/operator confirmations")
    config = load_real_config(arguments.real_config)
    if (
        config.controller.host is None
        or config.controller.datasheet_port is None
        or config.controller.device_sn is None
    ):
        parser.error("real config requires host, DataSheet port and DeviceSN")
    with DatasheetClient(
        config.controller.host,
        config.controller.datasheet_port,
        byte_order=arguments.byte_order,
        timeout_s=1.0,
        scope="private-read-only",
    ) as reader:
        sample = reader.poll()
    if sample is None:
        raise SystemExit("no complete DataSheet sample was received")
    if sample.device_sn != config.controller.device_sn:
        raise SystemExit("DataSheet DeviceSN does not match real config")
    if sample.moving or sample.error_code or any(sample.axis_error_codes):
        raise SystemExit("robot must be stationary and error-free before capture")
    payload = {
        "name": arguments.name,
        "split": arguments.split,
        "robot_joint_positions_deg": list(sample.joint_positions_deg),
        "visual_joint_positions_deg": list(arguments.visual_joints_deg),
        "robot_base_point_mm": list(sample.base_pose[:3]),
        "sofa_world_point_mm": list(arguments.sofa_world_point_mm),
        "robot_base_quaternion_xyzw": list(
            fixed_xyz_quaternion(sample.base_pose[3:6])
        ),
        "sofa_world_quaternion_xyzw": list(
            arguments.sofa_world_quaternion_xyzw
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
