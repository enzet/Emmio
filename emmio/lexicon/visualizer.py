"""Visualization of lexicons."""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib
from colour import Color
from matplotlib import dates as mdates
from matplotlib import pyplot as plt
from matplotlib import transforms as mtransforms
from svgwrite import Drawing

from emmio.language import Language
from emmio.lexicon.core import Lexicon, compute_lexicon_rate
from emmio.plot import Graph
from emmio.ui import Interface
from emmio.util import plus_week, week_start, year_end, year_start

DEFAULT_LEXICON_GRAPH: str = "lexicon.svg"


@dataclass
class LexiconRangeData:
    """Data for plotting lexicon rate change through time."""

    xs: list[datetime]
    """Time points."""

    y_ranges: list[list[float]]
    """Ranges of rates for each time point."""

    language: Language
    """Language of the lexicon."""

    def get_average_rate(self) -> float:
        """Get the average rate."""

        return sum(self.y_ranges[-1]) / len(self.y_ranges[-1])


@dataclass
class LexiconVisualizer:
    """Visualizer for lexicons."""

    interface: Interface
    """User interface for showing messages."""

    output_path: Path
    """Path to the output directory."""

    plot_main: bool = True
    """Plot main line."""

    plot_averages: bool = False
    """Fill between average lines."""

    plot_precise_values: bool = False
    """Plot marker for each user response."""

    plot_precision_interval: bool = False
    """Plot interval for precision."""

    precision: int = 100
    """How many wrong answers is needed to construct data point."""

    first_point: Callable[[datetime], datetime] = week_start
    """Function to compute starting point.

    It is based on the minimal point in time from data.
    """

    next_point: Callable[[datetime], datetime] = plus_week
    """Function to compute next point in time."""

    interactive: bool = True
    """Show the plot in a separate window."""

    def graph_with_matplot(
        self,
        lexicons: dict[Language, list[Lexicon]],
        legend: str | None = None,
        margin: float | None = None,
    ) -> None:
        """Plot lexicon rate change through time.

        :param lexicons: list of lexicons
        :param show_text: show labels on the current rate
        :param margin: do not show languages that never had rate over the margin
        """
        font: dict[str, float] = {"size": 8.0}
        matplotlib.rc("font", **font)

        fig, ax = plt.subplots()
        locator: mdates.YearLocator = mdates.YearLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        for side in ["top", "right", "bottom", "left"]:
            ax.spines[side].set_visible(False)

        x_min, x_max, lexicon_data = self.construct_lexicon_data(
            lexicons, margin if margin is not None else 0.0
        )

        for data_range in lexicon_data:
            color = data_range.language.get_color()
            title = data_range.language.get_name()
            if self.plot_main:
                plt.plot(
                    mdates.date2num(data_range.xs),
                    [sum(a) / len(a) for a in data_range.y_ranges],
                    color=color.hex,
                    linewidth=1,
                    label=title,
                )
            if self.plot_averages:
                for left, right, opacity in (
                    (0.0, 1.0, 0.1),
                    (0.2, 0.8, 0.15),
                    (0.4, 0.6, 0.2),
                ):
                    ys_1 = [
                        sorted(y_range)[int(left * len(y_range))]
                        for y_range in data_range.y_ranges
                    ]
                    ys_2 = [
                        sorted(y_range)[
                            min(int(right * len(y_range)), len(y_range) - 1)
                        ]
                        for y_range in data_range.y_ranges
                    ]
                    plt.fill_between(
                        mdates.date2num(data_range.xs),
                        ys_1,
                        ys_2,
                        color=color.hex,
                        alpha=opacity,
                        linewidth=0,
                    )
            if legend == "text":
                trans_offset = mtransforms.offset_copy(
                    ax.transData, fig=fig, x=0.1, y=0
                )
                plt.text(
                    mdates.date2num(data_range.xs[-1]),
                    sum(data_range.y_ranges[-1]) / len(data_range.y_ranges[-1]),
                    title,
                    transform=trans_offset,
                    color=color.hex,
                )

        for language, language_lexicons in lexicons.items():
            dates: list[datetime] = []
            responses: list[int] = []

            for lexicon in language_lexicons:
                dates += lexicon.dates
                responses += lexicon.responses

            date_ranges, rates = compute_lexicon_rate(
                sorted(zip(dates, responses)), self.precision
            )

            if self.plot_precise_values:
                plt.plot(
                    mdates.date2num([end for _, end in date_ranges]),
                    rates,
                    "o",
                    alpha=0.1,
                    markersize=0.5,
                    color=language.get_color().hex,
                )

            # If there are no data points, skip the language.
            if not date_ranges:
                continue

            if self.plot_precision_interval:
                plt.plot(
                    mdates.date2num([date_ranges[-1][0], date_ranges[-1][1]]),
                    [rates[-1], rates[-1]],
                    color=language.get_color().hex,
                )

        plt.title("Vocabulary level per language")
        if margin is not None:
            plt.ylim(ymin=margin)
        if x_min and x_max:
            plt.xlim(xmin=year_start(x_min), xmax=year_end(x_max))
        if legend == "list":
            plt.legend(loc="upper left", bbox_to_anchor=(1, 1), frameon=False)
        plt.subplots_adjust(left=0.3, right=0.7)

        if self.interactive:
            plt.show()
        else:
            plt.savefig(self.output_path / DEFAULT_LEXICON_GRAPH)
            self.interface.print(
                f"Graph saved to `{self.output_path / DEFAULT_LEXICON_GRAPH}`."
            )

    def graph_with_svg(
        self,
        lexicons: dict[Language, list[Lexicon]],
        margin: float | None,
        colors: list[Color] | None,
        background_color: Color,
        grid_color: Color,
    ) -> None:
        """Plot lexicon rate change through time into an SVG file.

        :param lexicons: mapping of languages to lexicons
        :param margin: do not show languages that never had rate over the margin
        :param colors: colors for each language
        :param background_color: background color
        """
        x_min, x_max, lexicon_data = self.construct_lexicon_data(
            lexicons, margin
        )
        data: list[tuple[list[datetime], list[float], Color, str]] = []
        for data_range in lexicon_data:
            language_name: str = data_range.language.get_self_name()
            language_name = language_name[0].upper() + language_name[1:]
            element = (
                data_range.xs,
                [
                    sorted(y_range)[int(0.5 * len(y_range))]
                    for y_range in data_range.y_ranges
                ],
                data_range.language.get_color(),
                language_name,
            )
            data.append(element)

        y_min: float = math.inf
        y_max: float = -math.inf

        for data_range in lexicon_data:
            y_min = min(
                y_min, min(min(y_range) for y_range in data_range.y_ranges)
            )
            y_max = max(
                y_max, max(max(y_range) for y_range in data_range.y_ranges)
            )

        if y_min == math.inf:
            y_min = 0.0
            y_max = 0.0

        if not x_min or not x_max:
            return

        graph: Graph = Graph(
            x_min,
            x_max,
            float(math.floor(y_min)),
            float(math.ceil(y_max + 0.25)),
            background_color=background_color,
            grid_color=grid_color,
            colors=colors,
        )

        svg: Drawing = Drawing(
            (self.output_path / DEFAULT_LEXICON_GRAPH).as_posix(),
            graph.canvas.size,
        )
        graph.draw_background(svg)
        graph.plot(svg, data)

        if self.plot_averages:
            for data_range in lexicon_data:
                for left, right, opacity in (
                    (0.0, 1.0, 0.1),
                    (0.2, 0.8, 0.15),
                    (0.4, 0.6, 0.2),
                ):
                    ys_1 = [
                        sorted(y_range)[int(left * len(y_range))]
                        for y_range in data_range.y_ranges
                    ]
                    ys_2 = [
                        sorted(y_range)[
                            min(int(right * len(y_range)), len(y_range) - 1)
                        ]
                        for y_range in data_range.y_ranges
                    ]
                    graph.fill_between(
                        svg,
                        data_range.xs,
                        ys_1,
                        ys_2,
                        color=data_range.language.get_color(),
                        opacity=opacity,
                    )
        graph.draw_grid(svg)
        graph.write(svg)
        self.interface.print(
            "Graph saved to "
            f"`{(self.output_path / DEFAULT_LEXICON_GRAPH).absolute()}`."
        )

    def get_lexicon_range_data(
        self,
        language: Language,
        language_lexicons: list[Lexicon],
        margin: float | None,
        skip_first_point: bool = True,
    ) -> LexiconRangeData | None:
        """Get data for plotting lexicon rate change through time.

        :param language: language
        :param language_lexicons: lexicons of the language
        :param margin: do not show languages that never had rate over the margin
        :param skip_first_point: skip first point in time
        """
        dates: list[datetime] = []
        responses: list[int] = []

        for lexicon in language_lexicons:
            dates += lexicon.dates
            responses += lexicon.responses

        date_ranges, rates = compute_lexicon_rate(
            sorted(zip(dates, responses)), self.precision
        )
        if not rates or (margin is not None and max(rates) < margin):
            return None

        xs: list[datetime] = []
        y_ranges: list[list[float]] = []

        point: datetime = self.first_point(min(end for _, end in date_ranges))

        if skip_first_point:
            point = self.next_point(point)

        current: list[float] = [rates[0]]

        index: int = 0
        for index, current_range in enumerate(date_ranges):
            _, end = current_range
            if point < end:
                while point < end:
                    xs.append(point)
                    y_ranges.append(current)
                    point = self.next_point(point)

                current = []

            current.append(rates[index])

        if index < len(rates):
            xs.append(point)
            y_ranges.append(current)

        return LexiconRangeData(xs, y_ranges, language)

    def construct_lexicon_data(
        self,
        lexicons: dict[Language, list[Lexicon]],
        margin: float | None,
        skip_first_point: bool = False,
    ) -> tuple[datetime | None, datetime | None, list[LexiconRangeData]]:
        """Construct data for plotting lexicon rate change through time.

        :param lexicons: mapping of languages to lexicons
        :param margin: do not show languages that never had rate over the margin
        :param skip_first_point: skip first point in time
        """
        data: list[LexiconRangeData] = []

        for language, language_lexicons in lexicons.items():
            data_range = self.get_lexicon_range_data(
                language, language_lexicons, margin, skip_first_point
            )
            if data_range:
                data.append(data_range)

        return (
            min(data_range.xs[0] for data_range in data) if data else None,
            max(data_range.xs[-1] for data_range in data) if data else None,
            sorted(
                data, key=lambda data: data.get_average_rate(), reverse=True
            ),
        )
