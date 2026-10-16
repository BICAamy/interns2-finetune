"""Read-only joint-center projections from the same FK used by SOFA meshes."""
from __future__ import annotations
import numpy as np


def project_joint_labels(link_transforms, image_shape, project):
    height, width = image_shape[:2]
    if height <= 0 or width <= 0 or len(link_transforms) != 6:
        return ()
    labels = []
    for index, transform in enumerate(link_transforms):
        # FK translations are millimetres; the SOFA scene uses metres.
        point = np.asarray(transform, dtype=np.float64)[:3, 3] / 1000.0
        if not np.all(np.isfinite(point)):
            continue
        try:
            row, column = project(point)
        except (ArithmeticError, ValueError, IndexError):
            continue
        if not np.isfinite(row) or not np.isfinite(column):
            continue
        if 0 <= row < height and 0 <= column < width:
            labels.append({"joint": index+1, "name": f"J{index+1}",
                           "x": float(column)/width, "y": float(row)/height})
    return tuple(labels)
