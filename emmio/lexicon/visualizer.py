from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Iterator

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
        lexicons: Iterator[Lexicon],
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

        x_min, x_max, data = self.construct_lexicon_data(lexicons, margin)

        for xs, ys, color, title in data:
            plt.plot(xs, ys, color=color.hex, linewidth=1, label=title)

        for lexicon in lexicons:
            dates, rates = lexicon.construct_precise(self.precision)
            language_name: str = lexicon.language.get_name()

            if self.plot_precise_values:
                plt.plot(
                    dates,
                    rates,
                    "o",
                    alpha=0.01,
                    markersize=0.5,
                    color=lexicon.language.get_color(),
                )

            if show_text:
                trans_offset = mtransforms.offset_copy(
                    ax.transData, fig=fig, x=0.1, y=0
                )
                plt.text(
                    dates[-1], rates[-1], language_name, transform=trans_offset
                )

        plt.legend(bbox_to_anchor=(1.05, 0.5), loc="center left", frameon=False)
        plt.ylim(ymin=margin)
        plt.xlim(xmin=year_start(x_min), xmax=year_end(x_max))
        plt.tight_layout()

        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")

    def graph_with_svg(self, lexicons, margin: float = 0.0):
        x_min, x_max, data = self.construct_lexicon_data(lexicons, margin)
        graph = Graph(data, x_min, x_max)
        graph.plot(Drawing("lexicon.svg", graph.canvas.size, fill="#101010"))

    def construct_lexicon_data(self, lexicons, margin):
        x_min: datetime | None = None
        data = []

        for lexicon in lexicons:

            lexicon: Lexicon
            dates, rates = lexicon.construct_precise(self.precision)

            if not rates or max(rates) < margin:
                continue

            language_name: str = lexicon.language.get_name()

            xs: list[datetime] = []
            ys: list[float] = []
            last: float | None = None

            point: datetime = self.first_point(min(dates))
            x_min = min(point, x_min) if x_min else point

            index: int = 0
            for index, current_point in enumerate(dates):
                while current_point > point:
                    if self.impulses and last is not None:
                        xs.append(point)
                        ys.append(last)
                    xs.append(point)
                    ys.append(rates[index])
                    last = rates[index]
                    point = self.next_point(point)

            if self.impulses and last is not None:
                xs.append(point)
                ys.append(last)
            if index < len(rates):
                xs.append(point)
                ys.append(rates[index])

            data.append((xs, ys, lexicon.language.get_color(), language_name))

        return x_min, point, sorted(data, key=lambda x: -x[1][-1])
