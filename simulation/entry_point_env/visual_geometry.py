"""Coordinate helpers shared by simulation and passive mirror visuals."""

from __future__ import annotations

from itertools import product
from math import isfinite
from typing import Sequence

from edge_gateway.transforms import matrix_from_translation_quaternion, transform_point


MM_PER_SCENE_UNIT = 1000.0


def real_workspace_scene_bounds(
    low_mm: Sequence[float],
    high_mm: Sequence[float],
    *,
    base_to_sofa_translation_mm: Sequence[float] | None = None,
    base_to_sofa_quaternion_xyzw: Sequence[float] | None = None,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return an axis-aligned SOFA box enclosing the configured Base workspace."""

    if len(low_mm) != 3 or len(high_mm) != 3:
        raise ValueError("real workspace bounds must contain three values")
    low = tuple(float(value) for value in low_mm)
    high = tuple(float(value) for value in high_mm)
    if not all(isfinite(value) for value in low + high):
        raise ValueError("real workspace bounds must be finite")
    if any(lower >= upper for lower, upper in zip(low, high)):
        raise ValueError("real workspace lower bounds must be below upper bounds")
    if (base_to_sofa_translation_mm is None) != (
        base_to_sofa_quaternion_xyzw is None
    ):
        raise ValueError("Base-to-SOFA translation and quaternion must be set together")

    corners: tuple[tuple[float, float, float], ...] = tuple(
        tuple(float(value) for value in corner)
        for corner in product(*zip(low, high))
    )
    if (
        base_to_sofa_translation_mm is not None
        and base_to_sofa_quaternion_xyzw is not None
    ):
        sofa_from_base = matrix_from_translation_quaternion(
            base_to_sofa_translation_mm,
            base_to_sofa_quaternion_xyzw,
        )
        corners = tuple(transform_point(sofa_from_base, corner) for corner in corners)

    low_scene = tuple(
        min(point[axis] for point in corners) / MM_PER_SCENE_UNIT
        for axis in range(3)
    )
    high_scene = tuple(
        max(point[axis] for point in corners) / MM_PER_SCENE_UNIT
        for axis in range(3)
    )
    return low_scene, high_scene  # type: ignore[return-value]
