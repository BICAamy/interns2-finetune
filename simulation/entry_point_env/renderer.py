"""RGB trajectory overlay independent from the SOFA rendering backend."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PIL import Image, ImageDraw
import numpy as np


PixelProjector = Callable[[np.ndarray], tuple[int, int]]
_AXIS_ORIGIN_SCENE = np.asarray((0.0, 0.0, 0.0), dtype=np.float64)
_AXIS_LENGTH_SCENE = 0.20  # 200 mm

_AXIS_SPECS = (
    ("X", np.asarray((1.0, 0.0, 0.0)), (255, 70, 70)),
    ("Y", np.asarray((0.0, 1.0, 0.0)), (70, 230, 90)),
    ("Z", np.asarray((0.0, 0.0, 1.0)), (70, 140, 255)),
)

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
    def _draw_arrow(
        self,
        image: np.ndarray,
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        self._draw_line(image, start, end, color)

        start_v = np.asarray(start, dtype=np.float64)
        end_v = np.asarray(end, dtype=np.float64)

        vector = end_v - start_v
        length = float(np.linalg.norm(vector))
        if length <= 1e-6:
            return

        unit = vector / length
        perpendicular = np.asarray((-unit[1], unit[0]))

        arrow_length = 10.0
        arrow_width = 5.0

        base = end_v - unit * arrow_length

        wing_a = base + perpendicular * arrow_width
        wing_b = base - perpendicular * arrow_width

        self._draw_line(
            image,
            (int(round(wing_a[0])), int(round(wing_a[1]))),
            end,
            color,
        )
        self._draw_line(
            image,
            (int(round(wing_b[0])), int(round(wing_b[1]))),
            end,
            color,
        )

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
        axis_labels: list[
            tuple[str, tuple[int, int], tuple[int, int, int]]
        ] = []

        axis_origin_pixel = project(_AXIS_ORIGIN_SCENE)

        for label, direction, color in _AXIS_SPECS:
            endpoint_scene = (
                _AXIS_ORIGIN_SCENE
                + direction * _AXIS_LENGTH_SCENE
            )
            endpoint_pixel = project(endpoint_scene)

            self._draw_arrow(
                output,
                axis_origin_pixel,
                endpoint_pixel,
                color,
            )

            self._draw_disk(
                output,
                endpoint_pixel,
                3,
                color,
            )

            axis_labels.append(
                (label, endpoint_pixel, color)
            )
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
        pil_image = Image.fromarray(output)
        draw = ImageDraw.Draw(pil_image)

        for label, (row, column), color in axis_labels:
            draw.text(
                (column + 5, row + 5),
                f"+{label}",
                fill=color,
                stroke_width=1,
                stroke_fill=(0, 0, 0),
            )

        output = np.asarray(pil_image, dtype=np.uint8).copy()
        return output

