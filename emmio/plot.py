"""Plotting utilities."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
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


def map_(
    value: float,
    current_min: float,
    current_max: float,
    target_min: float,
    target_max: float,
) -> float:
    """Remap value from current bounds to target bounds."""

    if current_max - current_min == 0:
        return target_min

    return target_min + (value - current_min) / (current_max - current_min) * (
        target_max - target_min
    )


def map_array(
    value: tuple[float, float],
    current_min: tuple[float, float],
    current_max: tuple[float, float],
    target_min: tuple[float, float],
    target_max: tuple[float, float],
) -> tuple[float, float]:
    """Remap array of values from current bounds to target bounds."""

    values: list[float] = [
        map_(
            value[index],
            current_min[index],
            current_max[index],
            target_min[index],
            target_max[index],
        )
        for index in range(2)
    ]
    return values[0], values[1]


@dataclass
class Canvas:
    """Canvas of the graph with workspace area."""

    size: tuple[float, float] = field(default_factory=lambda: (800.0, 600.0))
    """Width and height."""

    workspace: tuple[tuple[float, float], tuple[float, float]] = field(
        default_factory=lambda: (
            (100.0, 50.0),
            (250.0, 550.0),
        )
    )
    """Left top point; right bottom point."""


class Graph:
    """Graph with line and dots."""

    def __init__(
        self,
        min_x: datetime,
        max_x: datetime,
        min_y: float,
        max_y: float,
        canvas: Canvas = Canvas(),
        color: Color | list[Color] | None = Color("black"),
        background_color: Color = Color("white"),
        grid_color: Color = Color("#AAAAAA"),
    ) -> None:
        self.min_x: datetime = min_x
        self.max_x: datetime = max_x
        self.min_y: float = min_y
        self.max_y: float = max_y
        self.canvas: Canvas = canvas
        self.min_x_second: float = 0.0
        self.max_x_second = (
            (max_x - min_x).total_seconds() if max_x and min_x else 0
        )
        self.color: Color | list[Color] | None = color
        self.background_color: Color = background_color
        self.grid_color: Color = grid_color

        self.last_text_y: float = 0.0

    def map_(self, point: tuple[float, float]) -> tuple[float, float]:
        """Map point into the canvas."""
        return map_array(
            point,
            (self.min_x_second, self.max_y),
            (self.max_x_second, self.min_y),
            self.canvas.workspace[0],
            self.canvas.workspace[1],
        )

    def draw_background(self, svg: Drawing) -> None:
        """Draw background as a rectangle."""

        svg.add(
            svg.rect(
                insert=(0, 0),
                size=("100%", "100%"),
                rx=None,
                ry=None,
                fill=self.background_color.hex,
            )
        )

    def plot(
        self,
        svg: Drawing,
        data: list[tuple[list[datetime], list[float], Color, str]],
    ) -> None:
        """Plot data."""

        recolor: Color | None = None

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
            recolor = Color(gradient.get_funciri())

        last_text_y: float = 0.0

        for xs, ys, color, title in data:
            if recolor:
                color = recolor
            if not color and isinstance(self.color, Color):
                color = self.color

            assert len(xs) == len(ys)

            points: list[tuple[float, float]] = self.to_points(xs, ys)

            previous_point: tuple[float, float] | None = None
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

            if title and previous_point is not None:
                text_y = max(last_text_y + 15, previous_point[1] + 4)
                self.text(
                    svg,
                    (self.canvas.workspace[1][0] + 10, text_y),
                    title,
                    color.hex,
                )
                self.text(
                    svg,
                    (self.canvas.workspace[1][0] + 110, text_y),
                    f"{ys[-1]:.2f}",
                    color.hex,
                    anchor="end",
                )
                last_text_y = text_y

    def to_points(
        self, xs: list[datetime], ys: list[float]
    ) -> list[tuple[float, float]]:
        """Convert data to points on the canvas."""

        xs_second: list[float] = [(x - self.min_x).total_seconds() for x in xs]
        points: list[tuple[float, float]] = []

        for index, x in enumerate(xs_second):
            y = ys[index]
            mapped: tuple[float, float] = map_array(
                (x, y),
                (self.min_x_second, self.max_y),
                (self.max_x_second, self.min_y),
                self.canvas.workspace[0],
                self.canvas.workspace[1],
            )
            points.append(mapped)
        return points

    def fill_between(
        self,
        svg: Drawing,
        xs: list,
        ys_1: list,
        ys_2: list,
        color: Color | None = None,
        label: str | None = None,
        opacity: float | None = None,
    ) -> None:
        """Fill between two lines."""

        recolor: Color | None = None

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
            recolor = Color(gradient.get_funciri())

        last_text_y: int = 0

        if recolor:
            color = recolor
        if not color and isinstance(self.color, Color):
            color = self.color
        if not color:
            color = Color("black")

        assert len(xs) == len(ys_1)
        assert len(xs) == len(ys_2)

        points_1: list[tuple[float, float]] = self.to_points(xs, ys_1)
        points_2: list[tuple[float, float]] = self.to_points(xs, ys_2)

        points: list[tuple[float, float]] = points_1 + list(reversed(points_2))

        d: str = f"M {points[0][0]},{points[0][1]}"
        for point in points[1:]:
            d += f" L {point[0]},{point[1]}"
        d += " Z"

        line: Line = svg.path(d=d, fill=color, opacity=opacity)
        svg.add(line)
        if label:
            text_y = max(last_text_y + 15.0, points[-1][1] + 5.0)
            self.text(svg, (points[-1][0] + 15.0, text_y), label, color.hex)
            self.last_text_y = text_y

    def write(self, svg: Drawing) -> None:
        """Write the graph to a file."""

        with Path(svg.filename).open("w+", encoding="utf-8") as output_file:
            svg.write(output_file)

        logging.info("Graph was saved to `%s`.", Path(svg.filename).absolute())

    def draw_grid(self, svg: Drawing) -> None:
        """Draw grid."""

        group: Group = Group(opacity=0.25)
        for index in range(
            int(np.floor(self.min_y)), int(np.ceil(self.max_y)) + 1
        ):
            index_float: float = float(index)
            mapped_1: tuple[float, float] = self.map_((0.0, index_float))
            mapped_2: tuple[float, float] = self.map_(
                (self.max_x_second, index_float)
            )
            left = 110.0 if index_float in (self.min_y, self.max_y) else 0.0
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
                str(self.min_x.year - 1),
                self.grid_color.hex,
            )

            mapped_1 = self.map_((self.max_x_second, self.max_y))
            self.text(
                group,
                (mapped_1[0], mapped_1[1] + 15),
                str(self.max_x.year),
                self.grid_color.hex,
                anchor="end",
            )

    @staticmethod
    def text(
        svg: Union[Drawing, Group],
        point: tuple[float, float],
        text: str,
        color: str,
        anchor: str = "start",
    ) -> None:
        """Draw text"""
        text_element: Text = Text(
            text,
            point,
            font_size=12,
            font_family="SF Pro",
            fill=color,
            text_anchor=anchor,
        )
        svg.add(text_element)
