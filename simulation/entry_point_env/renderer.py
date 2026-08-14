"""RGB trajectory overlay independent from the SOFA rendering backend."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np


PixelProjector = Callable[[np.ndarray], tuple[int, int]]


class TrajectoryRenderer:
    """Draw TCP, entry point, and motion history onto a rendered RGB frame."""

    def __init__(self, *, line_radius: int = 1, marker_radius: int = 5) -> None:
        if line_radius < 0 or marker_radius <= 0:
            raise ValueError("renderer radii must be positive")
        self.line_radius = line_radius
        self.marker_radius = marker_radius

    @staticmethod
    def _draw_disk(
        image: np.ndarray,
        center: tuple[int, int],
        radius: int,
        color: tuple[int, int, int],
    ) -> None:
        row, column = center
        height, width = image.shape[:2]
        row_low = max(0, row - radius)
        row_high = min(height, row + radius + 1)
        column_low = max(0, column - radius)
        column_high = min(width, column + radius + 1)
        if row_low >= row_high or column_low >= column_high:
            return
        rows, columns = np.ogrid[row_low:row_high, column_low:column_high]
        mask = (rows - row) ** 2 + (columns - column) ** 2 <= radius * radius
        view = image[row_low:row_high, column_low:column_high]
        view[mask] = color

    def _draw_line(
        self,
        image: np.ndarray,
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        length = max(abs(end[0] - start[0]), abs(end[1] - start[1]), 1)
        rows = np.rint(np.linspace(start[0], end[0], length + 1)).astype(int)
        columns = np.rint(np.linspace(start[1], end[1], length + 1)).astype(int)
        for row, column in zip(rows, columns):
            self._draw_disk(image, (int(row), int(column)), self.line_radius, color)

    def render(
        self,
        frame: np.ndarray,
        *,
        trajectory_scene: Sequence[Sequence[float]],
        tcp_scene: Sequence[float],
        entry_scene: Sequence[float] | None,
        project: PixelProjector,
    ) -> np.ndarray:
        if not isinstance(frame, np.ndarray):
            raise TypeError("frame must be a numpy array")
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("frame must have shape HxWx3 and dtype uint8")

        output = frame.copy()
        projected_path = [project(np.asarray(point, dtype=np.float64)) for point in trajectory_scene]
        for start, end in zip(projected_path, projected_path[1:]):
            self._draw_line(output, start, end, (255, 215, 0))
        if entry_scene is not None:
            self._draw_disk(
                output,
                project(np.asarray(entry_scene, dtype=np.float64)),
                self.marker_radius,
                (0, 128, 255),
            )
        self._draw_disk(
            output,
            project(np.asarray(tcp_scene, dtype=np.float64)),
            self.marker_radius,
            (0, 255, 0),
        )
        return output

