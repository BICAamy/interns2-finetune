"""Small validated rigid-transform helpers shared by calibration and mirror code."""

from __future__ import annotations

from math import isfinite, sqrt
from typing import Sequence


Vector3 = tuple[float, float, float]
QuaternionXYZW = tuple[float, float, float, float]
Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


def _finite(values: Sequence[float], *, length: int, name: str) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)) or len(values) != length:
        raise ValueError(f"{name} must contain exactly {length} values")
    result = tuple(float(value) for value in values)
    if not all(isfinite(value) for value in result):
        raise ValueError(f"{name} must contain finite values")
    return result


def normalize_quaternion_xyzw(value: Sequence[float]) -> QuaternionXYZW:
    x, y, z, w = _finite(value, length=4, name="quaternion_xyzw")
    norm = sqrt(x * x + y * y + z * z + w * w)
    if norm < 1e-12:
        raise ValueError("quaternion_xyzw cannot have zero norm")
    normalized = (x / norm, y / norm, z / norm, w / norm)
    # q and -q encode the same rotation. Canonicalize for stable records/hashes.
    if normalized[3] < 0 or (normalized[3] == 0 and normalized[:3] < (0.0, 0.0, 0.0)):
        normalized = tuple(-component for component in normalized)
    return normalized  # type: ignore[return-value]


def matrix_from_translation_quaternion(
    translation_mm: Sequence[float], quaternion_xyzw: Sequence[float]
) -> Matrix4:
    tx, ty, tz = _finite(translation_mm, length=3, name="translation_mm")
    x, y, z, w = normalize_quaternion_xyzw(quaternion_xyzw)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy), tx),
        (2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx), ty),
        (2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy), tz),
        (0.0, 0.0, 0.0, 1.0),
    )


def transform_point(matrix: Sequence[Sequence[float]], point_mm: Sequence[float]) -> Vector3:
    point = _finite(point_mm, length=3, name="point_mm")
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("transform matrix must be 4x4")
    rows = tuple(_finite(row, length=4, name="transform row") for row in matrix)
    if any(abs(actual - expected) > 1e-9 for actual, expected in zip(rows[3], (0, 0, 0, 1))):
        raise ValueError("transform matrix must have a homogeneous final row")
    return tuple(
        rows[index][0] * point[0]
        + rows[index][1] * point[1]
        + rows[index][2] * point[2]
        + rows[index][3]
        for index in range(3)
    )  # type: ignore[return-value]


def quaternion_xyzw_from_rotation_matrix(matrix: Sequence[Sequence[float]]) -> QuaternionXYZW:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("rotation matrix must be 3x3")
    m = tuple(_finite(row, length=3, name="rotation row") for row in matrix)
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0:
        scale = sqrt(trace + 1.0) * 2
        result = (
            (m[2][1] - m[1][2]) / scale,
            (m[0][2] - m[2][0]) / scale,
            (m[1][0] - m[0][1]) / scale,
            0.25 * scale,
        )
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        scale = sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        result = (
            0.25 * scale,
            (m[0][1] + m[1][0]) / scale,
            (m[0][2] + m[2][0]) / scale,
            (m[2][1] - m[1][2]) / scale,
        )
    elif m[1][1] > m[2][2]:
        scale = sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        result = (
            (m[0][1] + m[1][0]) / scale,
            0.25 * scale,
            (m[1][2] + m[2][1]) / scale,
            (m[0][2] - m[2][0]) / scale,
        )
    else:
        scale = sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        result = (
            (m[0][2] + m[2][0]) / scale,
            (m[1][2] + m[2][1]) / scale,
            0.25 * scale,
            (m[1][0] - m[0][1]) / scale,
        )
    return normalize_quaternion_xyzw(result)
