"""Fit and validate Step 8 joint/Base calibration from an operator dataset."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .transforms import (
    matrix_from_translation_quaternion,
    normalize_quaternion_xyzw,
    quaternion_xyzw_from_rotation_matrix,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CalibrationSample(_Strict):
    name: str = Field(min_length=1, max_length=128)
    split: Literal["fit", "validation"]
    robot_joint_positions_deg: tuple[float, float, float, float, float, float]
    visual_joint_positions_deg: tuple[float, float, float, float, float, float]
    robot_base_point_mm: tuple[float, float, float]
    sofa_world_point_mm: tuple[float, float, float]
    robot_base_quaternion_xyzw: tuple[float, float, float, float]
    sofa_world_quaternion_xyzw: tuple[float, float, float, float]

    @field_validator("robot_base_quaternion_xyzw", "sofa_world_quaternion_xyzw")
    @classmethod
    def validate_quaternion(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        return normalize_quaternion_xyzw(value)


class CalibrationThresholds(_Strict):
    joint_rms_deg: float = Field(gt=0)
    joint_max_deg: float = Field(gt=0)
    base_rms_mm: float = Field(gt=0)
    base_max_mm: float = Field(gt=0)
    base_orientation_rms_deg: float = Field(gt=0)
    base_orientation_max_deg: float = Field(gt=0)


class CalibrationDataset(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    calibration_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    device_sn: str = Field(min_length=1, max_length=128)
    robot_model: str = Field(min_length=1, max_length=128)
    package_version: str = Field(min_length=1, max_length=128)
    captured_at: str = Field(min_length=1, max_length=64)
    thresholds: CalibrationThresholds
    samples: list[CalibrationSample] = Field(min_length=8)


class Residuals(_Strict):
    joint_rms_deg: float
    joint_max_deg: float
    base_rms_mm: float
    base_max_mm: float
    base_orientation_rms_deg: float
    base_orientation_max_deg: float


class CalibrationRecord(_Strict):
    schema_version: Literal["1.0"] = "1.0"
    calibration_id: str
    dataset_sha256: str
    device_sn: str
    robot_model: str
    package_version: str
    robot_axis_for_visual: tuple[int, int, int, int, int, int]
    joint_sign: tuple[int, int, int, int, int, int]
    joint_zero_offset_deg: tuple[float, float, float, float, float, float]
    sofa_from_robot_base_translation_mm: tuple[float, float, float]
    sofa_from_robot_base_quaternion_xyzw: tuple[float, float, float, float]
    fit_residuals: Residuals
    validation_residuals: Residuals
    accepted: bool


def _dataset_digest(dataset: CalibrationDataset) -> str:
    canonical = json.dumps(
        dataset.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _rounded(value: float, digits: int) -> float:
    result = round(float(value), digits)
    return 0.0 if result == 0.0 else result


def _fit_joint_mapping(samples: list[CalibrationSample]):
    robot = np.asarray([sample.robot_joint_positions_deg for sample in samples], dtype=float)
    visual = np.asarray([sample.visual_joint_positions_deg for sample in samples], dtype=float)
    candidates: dict[tuple[int, int], tuple[float, int, float]] = {}
    for visual_axis in range(6):
        for robot_axis in range(6):
            best = None
            for sign in (-1, 1):
                offset = float(np.mean(robot[:, robot_axis] - sign * visual[:, visual_axis]))
                predicted = sign * (robot[:, robot_axis] - offset)
                squared = float(np.sum((predicted - visual[:, visual_axis]) ** 2))
                if best is None or squared < best[0]:
                    best = (squared, sign, offset)
            assert best is not None
            candidates[(visual_axis, robot_axis)] = best
    permutation = min(
        itertools.permutations(range(6)),
        key=lambda axes: sum(candidates[(visual_axis, robot_axis)][0] for visual_axis, robot_axis in enumerate(axes)),
    )
    signs = tuple(candidates[(index, axis)][1] for index, axis in enumerate(permutation))
    offsets = tuple(candidates[(index, axis)][2] for index, axis in enumerate(permutation))
    return permutation, signs, offsets


def _fit_rigid(samples: list[CalibrationSample]):
    source = np.asarray([sample.robot_base_point_mm for sample in samples], dtype=float)
    target = np.asarray([sample.sofa_world_point_mm for sample in samples], dtype=float)
    if len(source) < 3 or np.linalg.matrix_rank(source - source.mean(axis=0)) < 2:
        raise ValueError("fit points must contain at least three non-collinear positions")
    source_center = source.mean(axis=0)
    target_center = target.mean(axis=0)
    left, _singular, right = np.linalg.svd((source - source_center).T @ (target - target_center))
    rotation = right.T @ left.T
    if np.linalg.det(rotation) < 0:
        right[-1, :] *= -1
        rotation = right.T @ left.T
    translation = target_center - rotation @ source_center
    return rotation, translation


def _residuals(
    samples: list[CalibrationSample], permutation, signs, offsets, rotation, translation
) -> Residuals:
    robot = np.asarray([sample.robot_joint_positions_deg for sample in samples], dtype=float)
    visual = np.asarray([sample.visual_joint_positions_deg for sample in samples], dtype=float)
    predicted_joints = np.column_stack([
        signs[index] * (robot[:, axis] - offsets[index])
        for index, axis in enumerate(permutation)
    ])
    joint_error = predicted_joints - visual
    source = np.asarray([sample.robot_base_point_mm for sample in samples], dtype=float)
    target = np.asarray([sample.sofa_world_point_mm for sample in samples], dtype=float)
    predicted_points = (rotation @ source.T).T + translation
    point_error = np.linalg.norm(predicted_points - target, axis=1)
    orientation_error_deg = []
    for sample in samples:
        robot_rotation = np.asarray(
            matrix_from_translation_quaternion(
                (0, 0, 0), sample.robot_base_quaternion_xyzw
            )
        )[:3, :3]
        sofa_rotation = np.asarray(
            matrix_from_translation_quaternion(
                (0, 0, 0), sample.sofa_world_quaternion_xyzw
            )
        )[:3, :3]
        difference = (rotation @ robot_rotation).T @ sofa_rotation
        cosine = float(np.clip((np.trace(difference) - 1.0) / 2.0, -1.0, 1.0))
        orientation_error_deg.append(float(np.rad2deg(np.arccos(cosine))))
    orientation_error = np.asarray(orientation_error_deg, dtype=float)
    return Residuals(
        joint_rms_deg=float(np.sqrt(np.mean(joint_error ** 2))),
        joint_max_deg=float(np.max(np.abs(joint_error))),
        base_rms_mm=float(np.sqrt(np.mean(point_error ** 2))),
        base_max_mm=float(np.max(point_error)),
        base_orientation_rms_deg=float(
            np.sqrt(np.mean(orientation_error ** 2))
        ),
        base_orientation_max_deg=float(np.max(orientation_error)),
    )


def solve_calibration(dataset: CalibrationDataset) -> CalibrationRecord:
    fit = [sample for sample in dataset.samples if sample.split == "fit"]
    validation = [sample for sample in dataset.samples if sample.split == "validation"]
    if len(fit) < 7 or not validation:
        raise ValueError("dataset requires at least seven fit samples and one validation sample")
    permutation, signs, offsets = _fit_joint_mapping(fit)
    if permutation != tuple(range(6)):
        raise ValueError(
            "robot axis order does not match J1..J6; current real config cannot safely represent a permutation"
        )
    rotation, translation = _fit_rigid(fit)
    fit_error = _residuals(fit, permutation, signs, offsets, rotation, translation)
    validation_error = _residuals(
        validation, permutation, signs, offsets, rotation, translation
    )
    threshold = dataset.thresholds
    accepted = all((
        fit_error.joint_rms_deg <= threshold.joint_rms_deg,
        validation_error.joint_rms_deg <= threshold.joint_rms_deg,
        fit_error.joint_max_deg <= threshold.joint_max_deg,
        validation_error.joint_max_deg <= threshold.joint_max_deg,
        fit_error.base_rms_mm <= threshold.base_rms_mm,
        validation_error.base_rms_mm <= threshold.base_rms_mm,
        fit_error.base_max_mm <= threshold.base_max_mm,
        validation_error.base_max_mm <= threshold.base_max_mm,
        fit_error.base_orientation_rms_deg <= threshold.base_orientation_rms_deg,
        validation_error.base_orientation_rms_deg <= threshold.base_orientation_rms_deg,
        fit_error.base_orientation_max_deg <= threshold.base_orientation_max_deg,
        validation_error.base_orientation_max_deg <= threshold.base_orientation_max_deg,
    ))
    return CalibrationRecord(
        calibration_id=dataset.calibration_id,
        dataset_sha256=_dataset_digest(dataset),
        device_sn=dataset.device_sn,
        robot_model=dataset.robot_model,
        package_version=dataset.package_version,
        robot_axis_for_visual=permutation,
        joint_sign=signs,
        joint_zero_offset_deg=tuple(_rounded(value, 9) for value in offsets),
        sofa_from_robot_base_translation_mm=tuple(
            _rounded(value, 9) for value in translation
        ),
        sofa_from_robot_base_quaternion_xyzw=tuple(
            _rounded(value, 12)
            for value in quaternion_xyzw_from_rotation_matrix(rotation)
        ),
        fit_residuals=fit_error,
        validation_residuals=validation_error,
        accepted=accepted,
    )


def load_dataset(path: str | Path) -> CalibrationDataset:
    selected = Path(path).expanduser().resolve(strict=True)
    if not selected.is_file() or selected.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("calibration dataset must be a regular JSON file below 2 MiB")
    return CalibrationDataset.model_validate_json(selected.read_text(encoding="utf-8"))


def write_calibrated_config(
    record: CalibrationRecord,
    *,
    source: str | Path,
    output: str | Path,
) -> Path:
    """Copy an operator config and replace only the accepted Step 8 fields."""
    if not record.accepted:
        raise ValueError("refusing to apply a calibration that failed residual thresholds")
    from robot_runtime.real_config import RealRobotConfig, load_real_config
    import yaml

    source_path = Path(source).expanduser().resolve(strict=True)
    output_path = Path(output).expanduser().resolve()
    if output_path.exists():
        raise ValueError("refusing to overwrite an existing calibrated config")
    config = load_real_config(source_path)
    if (
        config.controller.device_sn != record.device_sn
        or config.controller.model != record.robot_model
        or record.package_version not in config.controller.package_versions
    ):
        raise ValueError("calibration identity does not match the real config")
    data = config.model_dump(mode="json")
    data["joint_mapping"] = {
        "sign": list(record.joint_sign),
        "zero_offset_deg": list(record.joint_zero_offset_deg),
    }
    data["base_to_sofa"] = {
        "translation_mm": list(record.sofa_from_robot_base_translation_mm),
        "quaternion_xyzw": list(record.sofa_from_robot_base_quaternion_xyzw),
    }
    validated = RealRobotConfig.model_validate(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8") as file:
        yaml.safe_dump(
            validated.model_dump(mode="json"),
            file,
            allow_unicode=True,
            sort_keys=False,
        )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit Step 8 read-only robot calibration")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config-input", type=Path)
    parser.add_argument("--config-output", type=Path)
    arguments = parser.parse_args()
    if (arguments.config_input is None) != (arguments.config_output is None):
        parser.error("--config-input and --config-output must be supplied together")
    record = solve_calibration(load_dataset(arguments.dataset))
    if arguments.output.exists():
        raise SystemExit("refusing to overwrite an existing calibration record")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("x", encoding="utf-8") as file:
        file.write(record.model_dump_json(indent=2) + "\n")
    if arguments.config_input is not None and arguments.config_output is not None:
        write_calibrated_config(
            record,
            source=arguments.config_input,
            output=arguments.config_output,
        )
    print(record.model_dump_json(indent=2))
    return 0 if record.accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
