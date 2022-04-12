import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable

import matplotlib
import matplotlib.dates as mdates
import matplotlib.transforms as mtransforms
from matplotlib import pyplot as plt
from svgwrite import Drawing

from emmio.learning import Knowledge, Record, ResponseType
from emmio.lexicon import Lexicon
from emmio.plot import Graph
from emmio.util import first_day_of_week, year_end, year_start

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

colors = [
    "#CCCCCC",  # "#ff4444", "#ff8866", "#ffc183",
    "#b7c183", "#74c183", "#3e8a83", "#3e5583",
    "#3e0083", "#380073", "#300063", "#280053",
    "#200043", "#180033", "#100023", "#080013",
    "#000003", "#000000", "#000000", "#000000",
]  # fmt: skip


class Visualizer:
    def __init__(self):
        pass

    @staticmethod
    def get_commands() -> set[str]:
        return {
            "depth", "depth by time", "graph 2", "actions", "actions per day",
            "response time", "next question time"}

    def process_command(
        self, command: str, records: list[Record], knowledges
    ) -> bool:
        if command == "depth":
            self.depth(records)
        if command == "depth by time":
            self.depth(records, is_time=True)
        if command == "graph 2":
            self.graph_2(records)
        if command == "actions":
            self.actions(records)
        if command == "actions per day":
            self.cumulative_actions(records)
        if command == "response time":
            self.response_time(records)
        if command == "next question time":
            self.next_question_time(knowledges)
        return False

    def depth(
            self, records: list[Record], is_time: bool = False,
            show_text: bool = False):
        """
        Show depth graph.

        :param records: user responses
        :param is_time: if true, use time as x-axis, otherwise use actions count
        :param show_text: show depth labels
        """
        data = {}
        y = {}
        x = []

        knowledges = {}

        def idn(record: Record):
            return (
                f"{knowledges[record.question_id].get_depth()},"
                f"{knowledges[record.question_id].get_answers_number()}")

        count = 0

        for index, record in enumerate(records):  # type: (int, Record)
            if record.question_id in knowledges:
                data[idn(record)] -= 1
                # / (2 ** knowledges[record.question_id].get_depth())
            if not record.is_learning():
                continue
            last_answers = (
                knowledges[record.question_id].responses
                if record.question_id in knowledges else [])
            knowledges[record.question_id] = Knowledge(
                record.question_id, last_answers + [record.answer], record.time,
                record.interval)
            if idn(record) not in data:
                data[idn(record)] = 0
            data[idn(record)] += 1
            # / (2 ** knowledges[record.question_id].get_depth())
            x.append(record.time if is_time else count)
            count += 1
            s = 0
            for i in reversed(sorted(data.keys())):
                s += data[i]
                if i not in y:
                    y[i] = []
                y[i].append(s)

        fig, ax = plt.subplots()

        if is_time:
            locator = mdates.AutoDateLocator()
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

        for i in sorted(data.keys()):
            # plt.fill_between(range(len(y[i])), y[i], color=colors[i])
            # ax.fill_between(x, y[i], color=colors[i])
            depth, returns = map(lambda z: int(z) * 1, i.split(","))
            number = max(0, 255 - returns * 0 - depth * 10)
            # color =
            # f"#{hex(number)[2:]:>02}{hex(number)[2:]:>02}
            # {hex(number)[2:]:>02}"
            color = colors[depth + 1]
            plt.fill_between(
                x, [0] * (len(x) - len(y[i])) + y[i],
                color=color)

        plt.title("Question depth")
        plt.xlabel("Time" if is_time else "Actions")
        plt.ylabel("Questions")
        if not is_time:
            plt.xlim(xmin=0)
        plt.ylim(ymin=0)

        if show_text:
            trans_offset = mtransforms.offset_copy(
                ax.transData, fig=fig, x=0.1, y=0)

            for i in range(7):
                for j in range(10, 0, -1):
                    if f"{i},{j}" in y:
                        plt.text(
                            x[-1], y[f"{i},{j}"][-1], f"{2 ** i} days",
                            transform=trans_offset)
                        break

        plt.show()

    def actions(self, records: list[Record]):
        x, y = [], []
        count_learning: int = 0
        for record in records:  # type: Record
            if record.is_learning():
                count_learning += 1
            x.append(record.time)
            y.append(count_learning)
        plt.plot(x, range(len(x)), color="grey", linewidth=1)
        plt.plot(x, y, color="black", linewidth=1)
        plt.show()

    def cumulative_actions(self, records: list[Record]):
        data = {}
        for record in records:  # type: Record
            if not record.is_learning():
                continue
            time = datetime(
                day=record.time.day, month=record.time.month,
                year=record.time.year)
            if time not in data:
                data[time] = 0
            data[time] += 1
        plt.bar(
            sorted(data.keys()), [data[x] for x in sorted(data.keys())],
            color="black", linewidth=1)
        plt.show()

    def graph_2(self, records: list[Record]):
        x = []
        count: int = 0
        for record in records:  # type: Record
            if record.time + record.interval > datetime.now():
                count += 1
                x.append(record.time + record.interval)
        x = sorted(x)
        y = range(len(x))
        plt.plot(x, y)
        plt.show()

    def next_question_time(self, last_records: dict[str, Knowledge]):
        data = {}
        for word in last_records:  # type: str
            record = last_records[word]
            if record.interval.total_seconds() != 0:
                time = record.get_next_time()
                data[time] = random.random()  # time.hour * 60 + time.minute
        x = sorted(data.keys())
        y = list(map(lambda z: data[z], x))
        plt.plot(x, y, "o", color="black", markersize=0.5)
        plt.show()

    @staticmethod
    def response_time(
            records: list[Record], steps: int = 10,
            max_: int = 60) -> None:
        """
        Draw user response time histogram.

        :param records: user response records
        :param steps: number of histogram steps per second
        :param max_: maximum number of seconds to show
        """
        x: list[float] = [time / steps for time in range(0, max_ * steps + 1)]
        y_y: list[float] = [0.0] * (max_ * steps + 1)
        y_n: list[float] = [0.0] * (max_ * steps + 1)

        last_record: Optional[Record] = records[0] if records else None

        for record in records:  # type: Record
            interval: timedelta = record.time - last_record.time
            diff: int = int(interval.total_seconds() * steps)
            if interval.microseconds != 0 and diff / steps <= max_:
                (y_y if record.answer == ResponseType.RIGHT else y_n)[diff] += 1
            last_record = record

        plt.title("Response time")
        plt.xlabel("Time, seconds")
        plt.ylabel("Responses")
        plt.plot(x, y_y, color="green", linewidth=1)
        plt.plot(x, y_n, color="red", linewidth=1)
        plt.xlim(xmin=0, xmax=max_)
        plt.ylim(ymin=0)
        plt.show()


@dataclass
class LexiconVisualizer:

    # Plot marker for each user response.
    plot_precise_values: bool = False

    # How many wrong answers is needed to construct data point.
    precision: int = 100

    # Function to compute starting point in time based on the minimal point in
    # time from data.
    first_point: Callable = first_day_of_week

    # Function to compute next point in time.
    next_point: Callable = lambda x: x + timedelta(days=7)

    impulses: bool = True

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

        x_min, x_max, data = self.construct_lexicon_data(
            lexicons, margin
        )

        for xs, ys, color, title in data:
            plt.plot(xs, ys, color=color, linewidth=1, label=title)

        for lexicon in lexicons:
            dates, rates = lexicon.construct_precise(self.precision)
            language_name: str = lexicon.language.get_name()

            if self.plot_precise_values:
                plt.plot(
                    dates, rates, "o", alpha=0.01,
                    markersize=0.5, color=lexicon.language.get_color()
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
        plt.show()

    def graph_with_svg(self, lexicons, margin: float = 0.0):
        x_min, x_max, data = self.construct_lexicon_data(lexicons, margin)
        graph = Graph(data, x_min, x_max)
        graph.plot(Drawing("lexicon.svg", (800.0, 600.0)))

    def construct_lexicon_data(self, lexicons, margin):
        x_min: Optional[datetime] = None
        data = []

        for lexicon in lexicons:

            lexicon: Lexicon
            dates, rates = lexicon.construct_precise(self.precision)

            if not rates or max(rates) < margin:
                continue

            language_name: str = lexicon.language.get_name()

            xs: list[datetime] = []
            ys: list[float] = []
            last: Optional[float] = None

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

            data.append(
                (xs, ys, lexicon.language.get_color(), language_name)
            )

        return x_min, point, sorted(data, key=lambda x: -x[1][-1])
