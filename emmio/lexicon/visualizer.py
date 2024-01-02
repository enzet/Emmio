from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import matplotlib
from matplotlib import pyplot as plt, dates as mdates, transforms as mtransforms
from svgwrite import Drawing

from emmio.lexicon.core import Lexicon
from emmio.plot import Graph
from emmio.util import first_day_of_week, year_start, year_end


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
        lexicons: list[Lexicon],
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

        x_min, x_max, data = self.construct_lexicon_data(lexicons, margin)

        for xs, ys, color, title in data:
            plt.plot(
                xs,
                [sum(a) / len(a) for a in ys],
                color=color.hex,
                linewidth=1,
                label=title,
            )
            for step in 0, 0.25, 0.5, 0.75:
                plt.plot(
                    xs,
                    [a[int(len(a) * step)] for a in ys],
                    color=color.hex,
                    linewidth=1,
                    alpha=0.2,
                )
            plt.plot(
                xs, [a[-1] for a in ys], color=color.hex, linewidth=1, alpha=0.2
            )
            plt.fill_between(
                xs,
                [min(a) for a in ys],
                [max(a) for a in ys],
                color=color.hex,
                alpha=0.1,
            )
            if show_text:
                trans_offset = mtransforms.offset_copy(
                    ax.transData, fig=fig, x=0.1, y=0
                )
                plt.text(
                    xs[-1],
                    sum(ys[-1]) / len(ys[-1]),
                    title,
                    transform=trans_offset,
                    color=color.hex,
                )

        for lexicon in lexicons:
            dates, rates = lexicon.construct_precise(self.precision)

            if self.plot_precise_values:
                plt.plot(
                    dates,
                    rates,
                    "o",
                    alpha=0.1,
                    markersize=0.5,
                    color=lexicon.language.get_color().hex,
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

    def graph_with_svg(self, lexicons, margin: float = 0.0):
        x_min, x_max, lexicon_data = self.construct_lexicon_data(
            lexicons, margin
        )
        data = []
        for xs, y_ranges, color, title in lexicon_data:
            element = (
                xs,
                [
                    sorted(y_range)[int(0.5 * len(y_range))]
                    for y_range in y_ranges
                ],
                color,
                title,
            )
            data.append(element)
        data2 = []
        for xs, y_ranges, color, title in lexicon_data:
            element = (
                xs,
                [
                    [min(y_range) for y_range in y_ranges],
                    [max(y_range) for y_range in y_ranges],
                ],
                color,
                None,
            )
            data2.append(element)
        graph = Graph(x_min, x_max)  # , color=Color("#000000"))
        svg = Drawing("lexicon.svg", graph.canvas.size)
        graph.grid(svg)
        graph.plot(svg, data)
        for xs, y_ranges, color, title in lexicon_data:
            for left, right, opacity in (0.25, 0.75, 0.2), (0, 1, 0.1):
                ys_1 = [
                    sorted(y_range)[int(left * len(y_range))]
                    for y_range in y_ranges
                ]
                ys_2 = [
                    sorted(y_range)[
                        min(int(right * len(y_range)), len(y_range) - 1)
                    ]
                    for y_range in y_ranges
                ]
                graph.fill_between(
                    svg, xs, ys_1, ys_2, color=color, opacity=opacity
                )
        graph.write(svg)

    def construct_lexicon_data(self, lexicons, margin):
        x_min: datetime | None = None
        x_max: datetime | None = None
        data = []

        for lexicon in lexicons:
            lexicon: Lexicon
            dates, rates = lexicon.construct_precise(self.precision)

            if not rates or max(rates) < margin:
                continue

            language_name: str = lexicon.language.get_self_name()
            language_name = language_name[0].upper() + language_name[1:]

            xs: list[datetime] = []
            y_ranges: list[list[float]] = []

            point: datetime = self.first_point(min(dates))
            x_min = min(point, x_min) if x_min else point
            current = [rates[0]]

            index: int = 0
            for index, current_point in enumerate(dates):
                if point < current_point:
                    while point < current_point:
                        xs.append(point)
                        y_ranges.append(current)
                        point = self.next_point(point)
                        x_max = max(point, x_max) if x_max else point

                    current = []

                current.append(rates[index])

            if index < len(rates):
                xs.append(point)
                y_ranges.append(current)

            data.append(
                [
                    xs,
                    y_ranges,
                    lexicon.language.get_color(),
                    language_name,
                ]
            )

        return (
            x_min,
            x_max,
            sorted(data, key=lambda x: -sum(x[1][-1]) / len(x[1][-1])),
        )
