"""Capture one stationary Step 8 sample from receive-only DataSheet feedback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from robot_runtime.real_config import load_real_config
from simulation.entry_point_env.config import DEFAULT_CONFIG_PATH, EntryPointEnvConfig
from simulation.entry_point_env.kinematics import E05ProKinematics

from .transforms import quaternion_xyzw_from_rotation_matrix
from .huayan.adapter import fixed_xyz_quaternion
from .huayan.datasheet_client import DatasheetClient


def model_flange_pose(
    joint_positions_deg: tuple[float, ...],
    *,
    simulation_config: str | Path = DEFAULT_CONFIG_PATH,
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]]:
    config = EntryPointEnvConfig.from_yaml(simulation_config)
    kinematics = E05ProKinematics(
        joint_limits_deg=config.robot.joint_limits_deg,
        force_flange_offset_mm=config.robot.force_flange_offset_mm,
        tool_translation_mm=(0.0, 0.0, 0.0),
        tool_rpy_deg=(0.0, 0.0, 0.0),
    )
    flange = kinematics.forward(np.deg2rad(joint_positions_deg)).flange_transform
    return (
        tuple(float(value) for value in flange[:3, 3]),
        quaternion_xyzw_from_rotation_matrix(flange[:3, :3]),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture one stationary, receive-only calibration sample"
    )
    parser.add_argument("--real-config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--split", choices=("fit", "validation"), required=True)
    mapping = parser.add_mutually_exclusive_group(required=True)
    mapping.add_argument("--identity-joint-candidate", action="store_true")
    mapping.add_argument("--visual-joints-deg", type=float, nargs=6)
    parser.add_argument(
        "--simulation-config", type=Path, default=DEFAULT_CONFIG_PATH
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
    visual_joints = (
        tuple(float(value) for value in sample.joint_positions_deg)
        if arguments.identity_joint_candidate
        else tuple(arguments.visual_joints_deg)
    )
    sofa_point, sofa_quaternion = model_flange_pose(
        visual_joints,
        simulation_config=arguments.simulation_config,
    )
    payload = {
        "name": arguments.name,
        "split": arguments.split,
        "robot_joint_positions_deg": list(sample.joint_positions_deg),
        "visual_joint_positions_deg": list(visual_joints),
        "robot_base_point_mm": list(sample.base_pose[:3]),
        "sofa_world_point_mm": list(sofa_point),
        "robot_base_quaternion_xyzw": list(
            fixed_xyz_quaternion(sample.base_pose[3:6])
        ),
        "sofa_world_quaternion_xyzw": list(sofa_quaternion),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
