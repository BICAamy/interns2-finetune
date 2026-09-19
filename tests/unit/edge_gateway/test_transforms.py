from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from edge_gateway.calibration import load_dataset, solve_calibration, write_calibrated_config
from edge_gateway.transforms import (
    matrix_from_translation_quaternion,
    normalize_quaternion_xyzw,
    quaternion_xyzw_from_rotation_matrix,
    transform_point,
)


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/huayan/real_calibration_synthetic.json"


def test_rigid_transform_round_trip_and_canonical_quaternion() -> None:
    quaternion = normalize_quaternion_xyzw((0, 0, -2**0.5 / 2, -2**0.5 / 2))
    assert quaternion[3] > 0
    matrix = matrix_from_translation_quaternion((100, -50, 25), quaternion)
    assert transform_point(matrix, (10, 0, 0)) == pytest.approx((100, -40, 25))
    recovered = quaternion_xyzw_from_rotation_matrix(np.asarray(matrix)[:3, :3])
    assert recovered == pytest.approx(quaternion)
    with pytest.raises(ValueError):
        normalize_quaternion_xyzw((0, 0, 0, 0))


def test_synthetic_dataset_recovers_mapping_transform_and_validation() -> None:
    record = solve_calibration(load_dataset(FIXTURE))
    assert record.accepted
    assert record.robot_axis_for_visual == (0, 1, 2, 3, 4, 5)
    assert record.joint_sign == (1, -1, 1, -1, 1, -1)
    assert record.joint_zero_offset_deg == pytest.approx((1, -2, 3, -4, 5, -6))
    assert record.sofa_from_robot_base_translation_mm == pytest.approx((100, -50, 25))
    assert record.sofa_from_robot_base_quaternion_xyzw == pytest.approx((0, 0, 0, 1))
    assert record.validation_residuals.joint_max_deg < 1e-9
    assert record.validation_residuals.base_max_mm < 1e-9
    assert record.validation_residuals.base_orientation_max_deg < 1e-9


def test_validation_residual_over_threshold_is_not_accepted() -> None:
    dataset = load_dataset(FIXTURE)
    samples = list(dataset.samples)
    samples[-1] = samples[-1].model_copy(update={"sofa_world_point_mm": (150, 0, 85)})
    record = solve_calibration(dataset.model_copy(update={"samples": samples}))
    assert not record.accepted
    assert record.validation_residuals.base_max_mm > dataset.thresholds.base_max_mm


def test_orientation_validation_residual_over_threshold_is_not_accepted() -> None:
    dataset = load_dataset(FIXTURE)
    samples = list(dataset.samples)
    samples[-1] = samples[-1].model_copy(
        update={"sofa_world_quaternion_xyzw": (0, 0, 0.087155743, 0.996194698)}
    )
    record = solve_calibration(dataset.model_copy(update={"samples": samples}))
    assert not record.accepted
    assert (
        record.validation_residuals.base_orientation_max_deg
        > dataset.thresholds.base_orientation_max_deg
    )


def test_non_identity_axis_order_is_rejected_as_unrepresentable() -> None:
    dataset = load_dataset(FIXTURE)
    samples = []
    for sample in dataset.samples:
        visual = list(sample.visual_joint_positions_deg)
        visual[0], visual[1] = visual[1], visual[0]
        samples.append(sample.model_copy(update={"visual_joint_positions_deg": tuple(visual)}))
    with pytest.raises(ValueError, match="axis order"):
        solve_calibration(dataset.model_copy(update={"samples": samples}))


def test_accepted_record_is_applied_to_a_new_identity_matched_config(tmp_path: Path) -> None:
    import yaml

    from robot_runtime.real_config import RealRobotConfig, load_real_config

    record = solve_calibration(load_dataset(FIXTURE))
    source = tmp_path / "source.yaml"
    source.write_text(
        yaml.safe_dump(
            RealRobotConfig.model_validate({
                "controller": {
                    "device_sn": record.device_sn,
                    "model": record.robot_model,
                    "package_versions": [record.package_version],
                }
            }).model_dump(mode="json"),
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "calibrated.yaml"
    write_calibrated_config(record, source=source, output=output)
    calibrated = load_real_config(output)
    assert calibrated.joint_mapping.sign == record.joint_sign
    assert calibrated.joint_mapping.zero_offset_deg == pytest.approx(
        record.joint_zero_offset_deg
    )
    assert calibrated.base_to_sofa.translation_mm == pytest.approx(
        record.sofa_from_robot_base_translation_mm
    )
    with pytest.raises(ValueError, match="overwrite"):
        write_calibrated_config(record, source=source, output=output)
