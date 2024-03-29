import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Callable

import numpy as np
from matplotlib import pyplot as plt

from emmio import util
from emmio.learn.core import Knowledge, LearningRecord, Response, Learning
from emmio.learn.visualizer import LearningVisualizer, DEPTH_COLORS
from emmio.lexicon.core import Lexicon, AnswerType

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
        learnings: list[Learning],
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
            self.graph_3(learnings)
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
            self.graph_mistakes(learnings)
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
                depth: int = max(
                    0,
                    int(
                        np.log2(record.interval.total_seconds() / 60 / 60 / 24)
                    ),
                )
                data[depth + 1 + 2][point(record.time)] += 1
            else:
                data[0 + 2][point(record.time)] += 1

        for lexicon in lexicons:
            if not lexicon or "log" not in lexicon.logs:
                continue
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

    def graph_3(self, learnings: list[Learning]):
        records: list[tuple[str, LearningRecord]] = []

        for learning in learnings:
            for record in learning.process.records:
                if record.is_learning():
                    records.append((learning.id_, record))

        records = sorted(records, key=lambda x: x[1].time)

        x_list: list[datetime] = [x.time for _, x in records]
        min_x: datetime = min(x_list)
        max_x: datetime = util.day_start(datetime.now())
        days: int = int((max_x - min_x).total_seconds() / 3600 / 24)

        points = [
            util.day_start(min_x) + timedelta(days=i) for i in range(days + 1)
        ] + [datetime.now()]

        # Mapping: learning id -> last learning record.
        last_records: dict[str, LearningRecord] = {}
        data: dict[str, float] = {}

        xs = []
        values_map = {0.1: [], 0.15: [], 0.2: [], 0.25: [], 0.3: []}
        values_total = []

        index: int = 0

        for point in points:
            if index < len(records):
                while records[index][1].time < point:
                    learn_id, record = records[index]
                    id_ = f"{learn_id}_{record.question_id}"
                    last_records[id_] = record
                    if record.is_learning():
                        data[id_] = 1.0
                    index += 1
                    if index >= len(records):
                        break
            xs.append(point)

            values = {precision: 0 for precision in values_map}
            for record in last_records.values():
                if record.interval.total_seconds() > 0:
                    for coef in values_map:
                        values[coef] += max(
                            0.0,
                            (1 - coef)
                            ** ((point - record.time) / record.interval),
                        )
            for coef in values_map:
                values_map[coef].append(values[coef])
            values_total.append(len(last_records))

        values_map_bad = {
            pr: [v1 - v2 for v1, v2 in zip(values_map[pr], values_total)]
            for pr in values_map
        }
        plt.plot(xs, [0] * len(xs), color="black", linewidth=1)

        for map_ in values_map, values_map_bad:
            plt.plot(xs, map_[0.2], color="black", linewidth=1)
            for bottom, top in ((0.15, 0.25), (0.1, 0.3)):
                plt.fill_between(
                    xs, map_[bottom], map_[top], color="#00000022", linewidth=0
                )

        plt.xlim([min_x, points[-1]])
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

    def graph_mistakes(self, learnings):
        records: list[tuple[str, LearningRecord]] = []

        for learning in learnings:
            for record in learning.process.records:
                if record.is_learning():
                    records.append((learning.id_, record))

        size: int = 10
        xs = range(size)
        ys = [0] * size
        ns = [0] * size
        lasts = defaultdict(int)
        for learning_id, record in records:
            id_: str = f"{learning_id}_{record.question_id}"
            if record.response == Response.RIGHT:
                if id_ in lasts:
                    ys[lasts[id_]] += 1
                lasts[id_] += 1
            elif record.response == Response.WRONG:
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

        last_record: LearningRecord | None = records[0] if records else None

        for record in records:
            interval: timedelta = record.time - last_record.time
            diff: int = int(interval.total_seconds() * steps)
            if interval.microseconds != 0 and diff / steps <= max_:
                (y_y if record.response == Response.RIGHT else y_n)[diff] += 1
            last_record = record

        plt.title("Response time")
        plt.xlabel("Time, seconds")
        plt.ylabel("Responses")
        plt.plot(x, y_y, color="green", linewidth=1)
        plt.plot(x, y_n, color="red", linewidth=1)
        plt.xlim(xmin=0, xmax=max_)
        plt.ylim(ymin=0)
        self.plot()
