from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from svgwrite import Drawing
from svgwrite.shapes import Line


def map_(value, current_min, current_max, target_min, target_max):
    """
    Map current value in bounds of current_min and current_max to bounds of
    target_min and target_max.
    """
    if current_max - current_min == 0:
        return target_min
    else:
        return target_min + (value - current_min) / (
            current_max - current_min
        ) * (target_max - target_min)


def map_array(value, current_min, current_max, target_min, target_max):
    result = [None, None]
    for index in 0, 1:
        result[index] = map_(
            value[index],
            current_min[index],
            current_max[index],
            target_min[index],
            target_max[index],
        )
    return np.array((result[0], result[1]))


@dataclass
class Canvas:
    """
    Canvas of the graph with workspace area.
    """

    size: np.ndarray = np.array((800.0, 600.0))
    workspace: tuple[np.ndarray, np.ndarray] = (
        np.array((100.0, 50.0)),
        np.array((250.0, 550.0)),
    )


class Graph:
    """
    Graph with line and dots.
    """

    def __init__(
        self,
        data,
        min_x,
        max_x,
        canvas: Canvas = Canvas(),
    ):
        self.data = data
        self.min_x = min_x
        self.max_x = max_x
        self.canvas: Canvas = canvas
        self.min_y, self.max_y = 0, 7  # min(ys), max(ys)
        self.min_x_second = 0
        self.max_x_second = (max_x - min_x).total_seconds()

    def map_(self, point):
        """Map point into the canvas."""
        return map_array(
            point,
            np.array((self.min_x_second, self.max_y)),
            np.array((self.max_x_second, self.min_y)),
            self.canvas.workspace[0],
            self.canvas.workspace[1],
        )

    def plot(self, svg: Drawing) -> None:

        self.draw_grid(svg)
        last_text_y = 0

        for xs, ys, color, title in self.data:

            assert len(xs) == len(ys)

            xs_second: list[float] = [
                (x - self.min_x).total_seconds() for x in xs
            ]
            points = []

            for index, x in enumerate(xs_second):
                y = ys[index]
                mapped: np.ndarray = map_array(
                    np.array((x, y)),
                    np.array((self.min_x_second, self.max_y)),
                    np.array((self.max_x_second, self.min_y)),
                    self.canvas.workspace[0],
                    self.canvas.workspace[1],
                )
                points.append(mapped)
            previous_point: Optional[np.ndarray] = None

            for point in points:
                if previous_point is not None:
                    line: Line = svg.line(
                        (previous_point[0], previous_point[1]),
                        (point[0], point[1]),
                        stroke="#FFFFFF",
                        stroke_width=6,
                    )
                    svg.add(line)
                    line: Line = svg.line(
                        (previous_point[0], previous_point[1]),
                        (point[0], point[1]),
                        stroke=color,
                        stroke_width=2,
                    )
                    svg.add(line)
                previous_point = point

            for point in points:
                svg.add(svg.circle((point[0], point[1]), 5.5, fill="white"))
                svg.add(svg.circle((point[0], point[1]), 3.5, fill=color))

            title: str
            text_y = max(last_text_y + 15, point[1] + 6)
            self.text(svg, (point[0] + 15, text_y), title.upper(), color)
            last_text_y = text_y

        with Path(svg.filename).open("w+") as output_file:
            svg.write(output_file)

    def draw_grid(self, svg):

        for index in range(8):
            mapped_1: np.ndarray = self.map_((0, index))
            mapped_2: np.ndarray = self.map_((self.max_x_second, index))
            line: Line = svg.line(
                (mapped_1[0] - 50, mapped_1[1]),
                (mapped_2[0], mapped_2[1]),
                stroke="#DDDDDD",
                stroke_width=2,
            )
            self.text(
                svg, (mapped_1[0] - 28, mapped_1[1] + 18), str(index), "#DDDDDD"
            )
            svg.add(line)

    @staticmethod
    def text(svg, point, text, color) -> None:
        """Draw text"""
        text = svg.text(
            text,
            point,
            font_family="Montserrat",
            font_weight=600,
            letter_spacing=1,
            fill=color,
        )
        svg.add(text)
