import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import matplotlib
from matplotlib import pyplot as plt, dates as mdates, transforms as mtransforms
from svgwrite import Drawing

from emmio.language import Language
from emmio.lexicon.core import Lexicon, compute_lexicon_rate
from emmio.plot import Graph
from emmio.util import first_day_of_week, year_start, year_end


@dataclass
class LexiconRangeData:
    """Data for plotting lexicon rate change through time."""

    xs: list[datetime]
    y_ranges: list[list[float]]
    language: Language

    def get_average_rate(self) -> float:
        return sum(self.y_ranges[-1]) / len(self.y_ranges[-1])


@dataclass
class LexiconVisualizer:
    plot_precise_values: bool = False
    """Plot marker for each user response."""

    precision: int = 100
    """How many wrong answers is needed to construct data point."""

    first_point: Callable[[datetime], datetime] = first_day_of_week
    """
    Function to compute starting point in time based on the minimal point in
    time from data.
    """

    next_point: Callable[[datetime], datetime] = lambda x: x + timedelta(days=7)
    """Function to compute next point in time."""

    impulses: bool = True
    interactive: bool = True

    def graph_with_matplot(
        self,
        lexicons: dict[Language, list[Lexicon]],
        show_text: bool = False,
        margin: float = 0.0,
    ):
        """
        Plot lexicon rate change through time.

        :param lexicons: list of lexicons
        :param show_text: show labels on the current rate
        :param margin: do not show languages that never had rate over the margin
        """
        font: dict[str, float] = {"size": 8.0}
        matplotlib.rc("font", **font)

        fig, ax = plt.subplots()
        locator = mdates.YearLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_visible(False)

        x_min, x_max, lexicon_data = self.construct_lexicon_data(
            lexicons, margin
        )

        for data_range in lexicon_data:
            color = data_range.language.get_color()
            title = data_range.language.get_name()
            plt.plot(
                data_range.xs,
                [sum(a) / len(a) for a in data_range.y_ranges],
                color=color.hex,
                linewidth=1,
                label=title,
            )
            for step in 0, 0.25, 0.5, 0.75:
                plt.plot(
                    data_range.xs,
                    [a[int(len(a) * step)] for a in data_range.y_ranges],
                    color=color.hex,
                    linewidth=1,
                    alpha=0.2,
                )
            plt.plot(
                data_range.xs,
                [a[-1] for a in data_range.y_ranges],
                color=color.hex,
                linewidth=1,
                alpha=0.2,
            )
            plt.fill_between(
                data_range.xs,
                [min(a) for a in data_range.y_ranges],
                [max(a) for a in data_range.y_ranges],
                color=color.hex,
                alpha=0.1,
            )
            if show_text:
                trans_offset = mtransforms.offset_copy(
                    ax.transData, fig=fig, x=0.1, y=0
                )
                plt.text(
                    data_range.xs[-1],
                    sum(data_range.y_ranges[-1]) / len(data_range.y_ranges[-1]),
                    title,
                    transform=trans_offset,
                    color=color.hex,
                )

        for language, language_lexicons in lexicons.items():
            dates = []
            responses = []

            for lexicon in language_lexicons:
                dates += lexicon.dates
                responses += lexicon.responses

            date_ranges, rates = compute_lexicon_rate(
                sorted(zip(dates, responses)), self.precision
            )

            if self.plot_precise_values:
                plt.plot(
                    [end for _, end in date_ranges],
                    rates,
                    "o",
                    alpha=0.1,
                    markersize=0.5,
                    color=language.get_color().hex,
                )

        plt.title("Vocabulary level per language")
        plt.ylim(ymin=margin)
        plt.xlim(xmin=year_start(x_min), xmax=year_end(x_max))
        # plt.tight_layout()
        plt.subplots_adjust(left=0.3, right=0.7)

        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")

    def graph_with_svg(
        self, lexicons: dict[Language, list[Lexicon]], margin: float = 0.0
    ):
        x_min, x_max, lexicon_data = self.construct_lexicon_data(
            lexicons, margin
        )
        data = []
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

        graph = Graph(x_min, x_max)  # , color=Color("#000000"))
        svg = Drawing("lexicon.svg", graph.canvas.size)
        graph.grid(svg)
        graph.plot(svg, data)
        for data_range in lexicon_data:
            for left, right, opacity in (0.25, 0.75, 0.2), (0, 1, 0.1):
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
        graph.write(svg)

    def get_lexicon_range_data(
        self,
        language: Language,
        language_lexicons: list[Lexicon],
        margin: float,
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

        point: datetime = self.first_point(min([end for _, end in date_ranges]))

        if skip_first_point:
            point = self.next_point(point)

        current = [rates[0]]

        index: int = 0
        for index, current_range in enumerate(date_ranges):
            start, end = current_range
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
        margin: float,
        skip_first_point: bool = False,
    ) -> tuple[datetime, datetime, list[LexiconRangeData]]:
        data: list[LexiconRangeData] = []

        for language, language_lexicons in lexicons.items():
            data_range = self.get_lexicon_range_data(
                language, language_lexicons, margin, skip_first_point
            )
            if data_range:
                data.append(data_range)

        return (
            min(data_range.xs[0] for data_range in data),
            max(data_range.xs[-1] for data_range in data),
            sorted(
                data, key=lambda data: data.get_average_rate(), reverse=True
            ),
        )
