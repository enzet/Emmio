import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

import numpy as np
from colour import Color
from svgwrite import Drawing
from svgwrite.container import Group
from svgwrite.gradients import LinearGradient
from svgwrite.shapes import Line
from svgwrite.text import Text

GRADIENT: list[Color] = [
    Color("#00D45E"),
    Color("#83E507"),
    Color("#EDF013"),
    Color("#E77809"),
    Color("#E20000"),
]
GRADIENT_2: list[Color] = [
    Color("#00D45E"),
    Color("#83E507"),
    Color("#EDF013"),
    Color("#E77809"),
    Color("#E20000"),
]


def map_(value, current_min, current_max, target_min, target_max):
    """Remap value from current bounds to target bounds."""

    if current_max - current_min == 0:
        return target_min

    return target_min + (value - current_min) / (current_max - current_min) * (
        target_max - target_min
    )


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

    size: np.ndarray = field(default_factory=lambda: np.array((800.0, 600.0)))
    """Width and height."""

    workspace: tuple[np.ndarray, np.ndarray] = field(
        default_factory=lambda: (
            np.array((100.0, 50.0)),
            np.array((250.0, 550.0)),
        )
    )
    """Left top point; right bottom point."""


class Graph:
    """Graph with line and dots."""

    def __init__(
        self,
        min_x,
        max_x,
        min_y,
        max_y,
        canvas: Canvas = Canvas(),
        color: Color | list[Color] | str | None = Color("black"),
        background_color: Color = Color("white"),
        grid_color: Color = Color("#AAAAAA"),
    ):
        self.min_x = min_x
        self.max_x = max_x
        self.min_y = min_y
        self.max_y = max_y
        self.canvas: Canvas = canvas
        self.min_x_second = 0
        self.max_x_second = (
            (max_x - min_x).total_seconds() if max_x and min_x else 0
        )
        self.color: Color | list[Color] | str | None = color
        self.background_color: Color = background_color
        self.grid_color: Color = grid_color

        self.last_text_y = 0

    def map_(self, point):
        """Map point into the canvas."""
        return map_array(
            point,
            np.array((self.min_x_second, self.max_y)),
            np.array((self.max_x_second, self.min_y)),
            self.canvas.workspace[0],
            self.canvas.workspace[1],
        )

    def draw_background(self, svg) -> None:
        svg.add(
            svg.rect(
                insert=(0, 0),
                size=("100%", "100%"),
                rx=None,
                ry=None,
                fill=self.background_color.hex,
            )
        )

    def plot(self, svg: Drawing, data) -> None:
        recolor: str | None = None

        if isinstance(self.color, list):
            linear_gradient: LinearGradient = svg.linearGradient(
                self.map_((0, self.max_y)),
                self.map_((0, 0)),
                gradientUnits="userSpaceOnUse",
            )
            for index, color in enumerate(self.color):
                linear_gradient.add_stop_color(
                    index / (len(self.color) - 1), color.hex
                )

            gradient: LinearGradient = svg.defs.add(linear_gradient)
            recolor = gradient.get_funciri()

        last_text_y = 0

        for xs, ys, color, title in data:
            if recolor:
                color = recolor
            if not color:
                color = self.color

            assert len(xs) == len(ys)

            points = self.to_points(xs, ys)

            previous_point: np.ndarray | None = None
            for point in points:
                if previous_point is not None:
                    line: Line = svg.line(
                        (previous_point[0], previous_point[1]),
                        (point[0], point[1]),
                        stroke=color,
                        stroke_width=1,
                        stroke_linecap="round",
                    )
                    svg.add(line)
                previous_point = point

            if title and previous_point:
                text_y = max(last_text_y + 15, previous_point[1] + 4)
                self.text(
                    svg,
                    (self.canvas.workspace[1][0] + 10, text_y),
                    title,
                    color,
                )
                self.text(
                    svg,
                    (self.canvas.workspace[1][0] + 110, text_y),
                    f"{ys[-1]:.2f}",
                    color,
                    anchor="end",
                )
                last_text_y = text_y

    def to_points(self, xs: list, ys: list) -> list:
        xs_second: list[float] = [(x - self.min_x).total_seconds() for x in xs]
        points: list = []

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
        return points

    def fill_between(
        self, svg: Drawing, xs, ys_1, ys_2, color=None, label=None, opacity=None
    ) -> None:
        recolor: str | None = None

        if isinstance(self.color, list):
            linear_gradient: LinearGradient = svg.linearGradient(
                self.map_((0, self.max_y)),
                self.map_((0, 1)),
                gradientUnits="userSpaceOnUse",
            )
            for index, current_color in enumerate(self.color):
                linear_gradient.add_stop_color(
                    index / (len(self.color) - 1), current_color.hex
                )

            gradient: LinearGradient = svg.defs.add(linear_gradient)
            recolor = gradient.get_funciri()

        last_text_y: int = 0

        if recolor:
            color = recolor
        if not color:
            color = self.color

        assert len(xs) == len(ys_1)
        assert len(xs) == len(ys_2)

        points_1: list[np.ndarray] = self.to_points(xs, ys_1)
        points_2: list[np.ndarray] = self.to_points(xs, ys_2)

        points: list[np.ndarray] = points_1 + list(reversed(points_2))

        d: str = f"M {points[0][0]},{points[0][1]}"
        for point in points[1:]:
            d += f" L {point[0]},{point[1]}"
        d += " Z"

        line: Line = svg.path(d=d, fill=color, opacity=opacity)
        svg.add(line)
        if label:
            text_y = max(last_text_y + 15, points[-1][1] + 5)
            self.text(svg, (points[-1][0] + 15, text_y), label, color)
            self.last_text_y = text_y

    def write(self, svg):
        with Path(svg.filename).open("w+", encoding="utf-8") as output_file:
            svg.write(output_file)

        logging.info("Graph was saved to `%s`.", Path(svg.filename).absolute())

    def draw_grid(self, svg: Drawing) -> None:
        group: Group = Group(opacity=0.25)
        for index in range(self.min_y, self.max_y + 1):
            mapped_1: np.ndarray = self.map_((0, index))
            mapped_2: np.ndarray = self.map_((self.max_x_second, index))
            left = 110 if index in (self.min_y, self.max_y) else 0
            line: Line = group.add(
                Line(
                    (mapped_1[0] - 20, mapped_1[1]),
                    (mapped_2[0] + left, mapped_2[1]),
                    stroke=self.grid_color.hex,
                    stroke_width=1,
                )
            )
            if index != 0:
                self.text(
                    group,
                    (mapped_1[0] - 20, mapped_1[1] + 15),
                    str(index),
                    self.grid_color.hex,
                )
            group.add(line)
        svg.add(group)

        if self.min_x and self.max_x:
            mapped_1 = self.map_((self.min_x_second, self.max_y))
            self.text(
                group,
                (mapped_1[0], mapped_1[1] + 15),
                self.min_x.year - 1,
                self.grid_color.hex,
            )

            mapped_1 = self.map_((self.max_x_second, self.max_y))
            self.text(
                group,
                (mapped_1[0], mapped_1[1] + 15),
                self.max_x.year,
                self.grid_color.hex,
                anchor="end",
            )

    @staticmethod
    def text(
        svg: Union[Drawing, Group], point, text, color, anchor: str = "start"
    ) -> None:
        """Draw text"""
        text = Text(
            text,
            point,
            font_size=12,
            font_family="SF Pro",
            fill=color,
            text_anchor=anchor,
        )
        svg.add(text)
