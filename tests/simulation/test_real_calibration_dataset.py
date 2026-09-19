from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge_gateway.calibration import load_dataset, solve_calibration
from edge_gateway.calibration_capture import model_flange_pose
from simulation.entry_point_env.config import EntryPointEnvConfig
from simulation.entry_point_env.external_joint_state_controller import (
    ExternalJointStateController,
)
from tests.simulation.test_external_joint_state import telemetry


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/huayan/real_calibration_synthetic.json"
)


def test_accepted_record_drives_joint_mapping_and_base_to_sofa() -> None:
    record = solve_calibration(load_dataset(FIXTURE))
    assert record.accepted
    controller = ExternalJointStateController(
        EntryPointEnvConfig.from_yaml(),
        stale_ms=250,
        sign=record.joint_sign,
        zero_offset_deg=record.joint_zero_offset_deg,
        base_to_sofa_translation_mm=record.sofa_from_robot_base_translation_mm,
        base_to_sofa_quaternion_xyzw=record.sofa_from_robot_base_quaternion_xyzw,
    )
    state = telemetry(
        1,
        joints=(1.0, -2.0, 63.0, -4.0, 95.0, -6.0),
    )
    assert controller.apply_external_joint_state(state)
    snapshot = controller.snapshot
    assert snapshot is not None
    assert controller.coordinate_calibrated
    assert snapshot.visual_joint_positions_rad == pytest.approx(
        tuple(np.deg2rad((0.0, 0.0, 60.0, 0.0, 90.0, 0.0)))
    )
    np.testing.assert_allclose(
        snapshot.kinematics.flange_transform[:3, 3],
        snapshot.kinematics_robot_base.flange_transform[:3, 3]
        + np.asarray((100.0, -50.0, 25.0)),
    )
    assert snapshot.actual_tcp_sofa_world_mm == pytest.approx((601.0, -50.0, 525.0))
    assert controller.reason == "coordinate_calibrated_tool_tcp_unavailable"


def test_partial_coordinate_calibration_is_rejected() -> None:
    config = EntryPointEnvConfig.from_yaml()
    with pytest.raises(ValueError, match="provided together"):
        ExternalJointStateController(
            config,
            stale_ms=250,
            sign=(1, 1, 1, 1, 1, 1),
            zero_offset_deg=(0, 0, 0, 0, 0, 0),
            base_to_sofa_translation_mm=(0, 0, 0),
        )


def test_capture_reference_uses_zero_tool_flange_fk() -> None:
    joints = (0.0, 0.0, 60.0, 0.0, 90.0, 0.0)
    point, quaternion = model_flange_pose(joints)
    controller = ExternalJointStateController(
        EntryPointEnvConfig.from_yaml(), stale_ms=250
    )
    expected = controller.kinematics.forward(np.deg2rad(joints)).flange_transform
    assert point == pytest.approx(tuple(expected[:3, 3]))
    assert sum(value * value for value in quaternion) == pytest.approx(1.0)
