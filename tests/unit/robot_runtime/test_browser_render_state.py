from __future__ import annotations

from math import pi

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from robot_runtime.browser_render_state import e05_render_poses
from simulation.entry_point_env.kinematics import E05ProKinematics


def _kinematics() -> E05ProKinematics:
    return E05ProKinematics(
        joint_limits_deg=[(-360.0, 360.0)] * 6,
        force_flange_offset_mm=184.0,
        tool_translation_mm=(0.0, 0.0, 0.0),
        tool_rpy_deg=(0.0, 0.0, 0.0),
    )


@pytest.mark.parametrize(
    "joints_deg",
    [
        (0.0, 0.0, 60.0, 0.0, 90.0, 0.0),
        (25.0, -30.0, 72.0, 14.0, 48.0, -18.0),
        (-90.0, 45.0, -20.0, 80.0, -35.0, 120.0),
    ],
)
def test_browser_render_poses_match_authoritative_forward_kinematics(joints_deg):
    expected = _kinematics().forward(np.deg2rad(joints_deg))
    links, flange = e05_render_poses(joints_deg)

    assert len(links) == 6
    expected_transforms = (*expected.link_transforms, expected.flange_transform)
    actual_poses = (*links, flange)
    for actual, transform in zip(actual_poses, expected_transforms):
        assert actual["position_m"] == pytest.approx(transform[:3, 3] / 1000.0)
        actual_rotation = Rotation.from_quat(actual["quaternion_xyzw"]).as_matrix()
        assert actual_rotation == pytest.approx(transform[:3, :3], abs=1e-12)


def test_browser_render_poses_reject_invalid_joint_state():
    with pytest.raises(ValueError, match="six values"):
        e05_render_poses((0.0,) * 5)
    with pytest.raises(ValueError, match="finite"):
        e05_render_poses((0.0, 0.0, 0.0, pi, float("nan"), 0.0))
