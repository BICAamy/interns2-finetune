"""Offline Step 11 IK checks against the independently captured Step 8 pose."""

from __future__ import annotations

import math

from edge_gateway.commissioning_runtime import make_path_ik
from robot_runtime.real_config import JointMapping, RealRobotConfig
from surgical_contracts import CoordinateFrame, DistanceUnit, Pose6D, RobotTelemetry


def test_step8_independent_pose_supports_bounded_one_mm_axis_paths():
    # Values captured at the independent combination-validation pose in Step 8.
    joints = (2.509, -22.981, 87.889, -0.887, 54.549, -62.159)
    pose = Pose6D(
        translation_mm=(586.632, 23.386, 242.192),
        rotation_rpy_deg=(0.0, 0.0, 0.0),
        quaternion_xyzw=(-0.5336041527480774, 0.8361309346678548,
                         -0.06903915358631091, 0.10670175037716965),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )
    telemetry = RobotTelemetry.model_construct(
        joint_positions_deg=joints, actual_pose_robot_base=pose,
    )
    config = RealRobotConfig.model_construct(
        joint_mapping=JointMapping(sign=(1,) * 6, zero_offset_deg=(0.0,) * 6),
    )
    for axis in range(3):
        for direction in (-1.0, 1.0):
            solve = make_path_ik(config, telemetry)
            for index in range(11):
                xyz = list(pose.translation_mm)
                xyz[axis] += direction * index / 10
                solved = solve(tuple(xyz))
                assert len(solved) == 6
                assert all(math.isfinite(value) for value in solved)


def test_ik_rejects_pose_that_disagrees_with_calibrated_flange():
    joints = (2.509, -22.981, 87.889, -0.887, 54.549, -62.159)
    pose = Pose6D(
        translation_mm=(600.0, 23.386, 242.192),
        rotation_rpy_deg=(0.0, 0.0, 0.0),
        quaternion_xyzw=(-0.5336041527480774, 0.8361309346678548,
                         -0.06903915358631091, 0.10670175037716965),
        frame=CoordinateFrame.ROBOT_BASE,
        unit=DistanceUnit.MILLIMETER,
    )
    telemetry = RobotTelemetry.model_construct(
        joint_positions_deg=joints, actual_pose_robot_base=pose,
    )
    config = RealRobotConfig.model_construct(
        joint_mapping=JointMapping(sign=(1,) * 6, zero_offset_deg=(0.0,) * 6),
    )
    import pytest
    with pytest.raises(ValueError, match="FK disagrees"):
        make_path_ik(config, telemetry)
