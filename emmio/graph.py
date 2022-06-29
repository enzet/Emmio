import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable

import matplotlib
import matplotlib.dates as mdates
import matplotlib.transforms as mtransforms
import numpy as np
from matplotlib import pyplot as plt
from svgwrite import Drawing

from emmio import util
from emmio.learning.core import Knowledge, LearningRecord, ResponseType
from emmio.learning.visualizer import LearningVisualizer, DEPTH_COLORS
from emmio.lexicon import Lexicon, AnswerType
from emmio.plot import Graph
from emmio.util import first_day_of_week, year_end, year_start

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Visualizer:
    def __init__(self, interactive: bool = True):
        self.interactive: bool = interactive

    @staticmethod
    def get_commands() -> set[str]:
        return {
            "plot learn",
            "plot learn by time",
            "plot learn by depth",
            "plot learn by time by depth",
            "graph 2",
            "graph 3",
            "actions",
            "actions per day",
            "actions per week",
            "actions per month",
            "actions per year",
            "response time",
            "next question time",
            "mistakes",
        }

    def process_command(
        self,
        command: str,
        records: list[LearningRecord],
        knowledges,
        lexicons: list[Lexicon],
    ) -> bool:
        if command == "plot learn":
            LearningVisualizer(records, interactive=self.interactive).draw()
        if command == "plot learn by time":
            LearningVisualizer(
                records, interactive=self.interactive, is_time=True
            ).draw()
        if command == "plot learn by depth":
            LearningVisualizer(
                records, interactive=self.interactive, count_by_depth=True
            ).draw()
        if command == "plot learn by time by depth":
            LearningVisualizer(
                records,
                interactive=self.interactive,
                is_time=True,
                count_by_depth=True,
            ).draw()
        if command == "graph 2":
            self.graph_2(records)
        if command == "graph 3":
            self.graph_3(records)
        if command == "actions":
            self.actions(records)
        if command == "actions per day":
            self.cumulative_actions(
                records,
                lexicons,
                lambda x: datetime(day=x.day, month=x.month, year=x.year),
                1,
            )
        if command == "actions per week":
            self.cumulative_actions(
                records, lexicons, util.first_day_of_week, 7
            )
        if command == "actions per month":
            self.cumulative_actions(
                records, lexicons, util.first_day_of_month, 31
            )
        if command == "actions per year":
            self.cumulative_actions(
                records, lexicons, util.year_start, 365 * 0.6
            )
        if command == "response time":
            self.response_time(records)
        if command == "next question time":
            self.next_question_time(knowledges)
        if command == "mistakes":
            self.graph_mistakes(records)
        return False

    def plot(self):
        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")

    def actions(self, records: list[LearningRecord]):
        x, y = [], []
        count_learning: int = 0
        for record in records:
            if record.is_learning():
                count_learning += 1
            x.append(record.time)
            y.append(count_learning)
        plt.plot(x, range(len(x)), color="grey", linewidth=1)
        plt.plot(x, y, color="black", linewidth=1)
        self.plot()

    def cumulative_actions(
        self,
        records: list[LearningRecord],
        lexicons: list[Lexicon],
        point: Callable,
        width: float,
    ):
        size: int = 20
        data: list[dict[str, int]] = [defaultdict(int) for _ in range(size)]

        for record in records:
            if record.interval:
                depth = int(
                    np.log2(record.interval.total_seconds() / 60 / 60 / 24)
                )
                data[depth + 1 + 2][point(record.time)] += 1
            else:
                data[0 + 2][point(record.time)] += 1

        for lexicon in lexicons:
            last_record = lexicon.logs["log"].records[0]
            for record in lexicon.logs["log"].records:
                if (
                    record.answer_type == AnswerType.USER_ANSWER
                    or record.answer_type == AnswerType.UNKNOWN
                    and (record.time - last_record.time).total_seconds() > 0
                ):
                    data[0][point(record.time)] += 1
                last_record = record
            if "log_ex" in lexicon.logs:
                for record in lexicon.logs["log_ex"].records:
                    if record.answer_type in [
                        AnswerType.UNKNOWN,
                        AnswerType.USER_ANSWER,
                    ]:
                        data[1][point(record.time)] += 1

        keys = set()
        for i in range(size):
            keys |= data[i].keys()

        xs = sorted(keys)

        for i in range(size):
            if i == 0:  # log
                color = "#E8F0F8"
                label = "Checking lexicon"
            elif i == 1:  # log_ex
                color = "#D8E0E8"
                label = "Checking new words"
            else:
                color = DEPTH_COLORS[i + 1 - 2]
                label = f"Learning level {i + 1 - 2}"

            ys = [sum(data[y][x] for y in range(i, size)) for x in xs]

            if np.any(ys):
                plt.bar(
                    xs,
                    ys,
                    color=color,
                    linewidth=0,
                    width=width,
                    label=label,
                )
        plt.legend(loc="center left", frameon=False)
        self.plot()

    def graph_2(self, records: list[LearningRecord]):
        x = []
        count: int = 0
        for record in records:
            if record.time + record.interval > datetime.now():
                count += 1
                x.append(record.time + record.interval)
        x = sorted(x)
        y = range(len(x))
        plt.plot(x, y)
        self.plot()

    def graph_3(self, records: list[LearningRecord]):
        x_list = [x.time for x in records]
        min_x = min(x_list)
        max_x = max(x_list)
        point = util.day_start(min_x)

        last_records: dict[str, LearningRecord] = {}
        data: dict[str, float] = {}
        index: int = 0

        xs = []
        ys = []
        ys2 = []
        ys3 = []

        while point < max_x:
            while records[index].time < point:
                id_ = f"{records[index].course_id}_{records[index].question_id}"
                last_records[id_] = records[index]
                if records[index].is_learning():
                    data[id_] = 1.0
                index += 1
            xs.append(point)
            y = 0
            y2 = 0
            for record in last_records.values():
                if record.time + record.interval > point:
                    y += 1
                if record.interval.total_seconds() > 0:
                    y2 += 1 - 0.2 * min(
                        5, (point - record.time) / record.interval
                    )
            y3 = 0
            for id_ in data:
                data[id_] *= 0.99
                y3 += data[id_]
            ys.append(y)
            ys2.append(y2)
            ys3.append(y3)
            point += timedelta(days=1)

        plt.plot(xs, ys)
        plt.plot(xs, ys2)
        plt.plot(xs, ys3)
        self.plot()

    def next_question_time(self, last_records: dict[str, Knowledge]):
        data = {}
        for word in last_records:
            record = last_records[word]
            if record.interval.total_seconds() != 0:
                time = record.get_next_time()
                data[time] = random.random()  # time.hour * 60 + time.minute
        x = sorted(data.keys())
        y = list(map(lambda z: data[z], x))
        plt.plot(x, y, "o", color="black", markersize=0.5)
        self.plot()

    def graph_mistakes(self, records: list[LearningRecord]):
        size: int = 7
        xs = range(size)
        ys = [0] * size
        ns = [0] * size
        lasts = defaultdict(int)
        for record in records:
            id_: str = f"{record.course_id}_{record.question_id}"
            if record.answer == ResponseType.RIGHT:
                if id_ in lasts:
                    ys[lasts[id_]] += 1
                lasts[id_] += 1
            elif record.answer == ResponseType.WRONG:
                if id_ in lasts:
                    ns[lasts[id_]] += 1
                lasts[id_] = 0
        # plt.plot(xs, [(ns[i] + ys[i]) for i in range(size)])
        plt.plot(
            xs,
            [
                (ns[i] / (ns[i] + ys[i]) * 100 if (ns[i] + ys[i] > 0) else 0)
                for i in range(size)
            ],
        )
        plt.ylim(ymin=0)
        plt.xlim([0, size - 1])
        self.plot()

    def response_time(
        self, records: list[LearningRecord], steps: int = 10, max_: int = 60
    ) -> None:
        """
        Draw user response time histogram.

        :param records: user response records
        :param steps: number of histogram steps per second
        :param max_: maximum number of seconds to show
        """
        x: list[float] = [time / steps for time in range(0, max_ * steps + 1)]
        y_y: list[float] = [0.0] * (max_ * steps + 1)
        y_n: list[float] = [0.0] * (max_ * steps + 1)

        last_record: Optional[LearningRecord] = records[0] if records else None

        for record in records:
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
        self.plot()


@dataclass
class LexiconVisualizer:

    # Plot marker for each user response.
    plot_precise_values: bool = False

    # How many wrong answers is needed to construct data point.
    precision: int = 100

    # Function to compute starting point in time based on the minimal point in
    # time from data.
    first_point: Callable[[datetime], datetime] = first_day_of_week

    # Function to compute next point in time.
    next_point: Callable[[datetime], datetime] = lambda x: x + timedelta(days=7)

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

            data.append((xs, ys, lexicon.language.get_color(), language_name))

        return x_min, point, sorted(data, key=lambda x: -x[1][-1])
