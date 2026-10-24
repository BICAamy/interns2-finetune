"""Small, dependency-free E05-Pro forward kinematics for browser rendering.

The browser is deliberately a visualization client only.  This module turns
the already-authoritative joint feedback into absolute link poses; it is not
used for IK, planning, validation, or control.
"""

from __future__ import annotations

from math import cos, isfinite, pi, sin, sqrt
from typing import Sequence


Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


# The same verified 485/elfin5 chain used by
# simulation.entry_point_env.kinematics.E05ProKinematics.
JOINT_ORIGINS = (
    ((0.0, 0.0, 220.0), (0.0, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, 0.0)),
    ((0.0, 380.0, 0.0), (-pi, 0.0, pi / 2.0)),
    ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, pi / 2.0)),
    ((0.0, 0.0, 420.0), (-pi / 2.0, 0.0, 0.0)),
    ((0.0, 0.0, 0.0), (pi / 2.0, 0.0, 0.0)),
)


def _multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(
            sum(left[row][inner] * right[inner][column] for inner in range(4))
            for column in range(4)
        )
        for row in range(4)
    )  # type: ignore[return-value]


def _transform(
    translation_mm: Sequence[float] = (0.0, 0.0, 0.0),
    rpy_rad: Sequence[float] = (0.0, 0.0, 0.0),
) -> Matrix4:
    x, y, z = (float(value) for value in translation_mm)
    roll, pitch, yaw = (float(value) for value in rpy_rad)
    cr, sr = cos(roll), sin(roll)
    cp, sp = cos(pitch), sin(pitch)
    cy, sy = cos(yaw), sin(yaw)
    # scipy Rotation.from_euler("xyz", rpy).as_matrix()
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y),
        (-sp, cp * sr, cp * cr, z),
        (0.0, 0.0, 0.0, 1.0),
    )


def _quaternion_xyzw(matrix: Matrix4) -> tuple[float, float, float, float]:
    m = matrix
    trace = m[0][0] + m[1][1] + m[2][2]
    if trace > 0.0:
        scale = sqrt(trace + 1.0) * 2.0
        value = (
            (m[2][1] - m[1][2]) / scale,
            (m[0][2] - m[2][0]) / scale,
            (m[1][0] - m[0][1]) / scale,
            0.25 * scale,
        )
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        scale = sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        value = (
            0.25 * scale,
            (m[0][1] + m[1][0]) / scale,
            (m[0][2] + m[2][0]) / scale,
            (m[2][1] - m[1][2]) / scale,
        )
    elif m[1][1] > m[2][2]:
        scale = sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        value = (
            (m[0][1] + m[1][0]) / scale,
            0.25 * scale,
            (m[1][2] + m[2][1]) / scale,
            (m[0][2] - m[2][0]) / scale,
        )
    else:
        scale = sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        value = (
            (m[0][2] + m[2][0]) / scale,
            (m[1][2] + m[2][1]) / scale,
            0.25 * scale,
            (m[1][0] - m[0][1]) / scale,
        )
    norm = sqrt(sum(component * component for component in value))
    normalized = tuple(component / norm for component in value)
    if normalized[3] < 0.0:
        normalized = tuple(-component for component in normalized)
    return normalized  # type: ignore[return-value]


def _pose(matrix: Matrix4) -> dict[str, tuple[float, ...]]:
    return {
        "position_m": (
            matrix[0][3] / 1000.0,
            matrix[1][3] / 1000.0,
            matrix[2][3] / 1000.0,
        ),
        "quaternion_xyzw": _quaternion_xyzw(matrix),
    }


def e05_render_poses(
    joint_positions_deg: Sequence[float],
    *,
    force_flange_offset_mm: float = 184.0,
) -> tuple[list[dict[str, tuple[float, ...]]], dict[str, tuple[float, ...]]]:
    """Return six absolute link poses plus the force-flange pose.

    All output positions are metres in robot Base.  The function accepts only
    measured/simulated joint state and cannot produce a robot command.
    """

    if len(joint_positions_deg) != 6:
        raise ValueError("joint_positions_deg must contain six values")
    joints = tuple(float(value) * pi / 180.0 for value in joint_positions_deg)
    if not all(isfinite(value) for value in joints):
        raise ValueError("joint_positions_deg must be finite")
    flange_offset = float(force_flange_offset_mm)
    if not isfinite(flange_offset) or flange_offset <= 0.0:
        raise ValueError("force_flange_offset_mm must be positive")

    world_from_link: Matrix4 = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    link_poses: list[dict[str, tuple[float, ...]]] = []
    for (translation_mm, rpy_rad), joint_angle in zip(JOINT_ORIGINS, joints):
        world_from_link = _multiply(
            _multiply(world_from_link, _transform(translation_mm, rpy_rad)),
            _transform(rpy_rad=(0.0, 0.0, joint_angle)),
        )
        link_poses.append(_pose(world_from_link))

    flange = _multiply(
        world_from_link,
        _transform((0.0, 0.0, flange_offset)),
    )
    return link_poses, _pose(flange)

