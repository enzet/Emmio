import random
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

import numpy as np
from matplotlib import dates as mdates
from matplotlib import pyplot as plt
from tqdm import tqdm

from emmio import util
from emmio.language import Language
from emmio.learn.core import Knowledge, Learning, LearningRecord, Response
from emmio.learn.visualizer import DEPTH_COLORS  # type: ignore
from emmio.lexicon.core import AnswerType, Lexicon, LexiconLogRecord

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.util import day_start

HATCHES: list[str] = [x + x for x in ".oO/\\|-+x*"]


class Visualizer:
    def __init__(self, interactive: bool = True):
        self.interactive: bool = interactive

    def plot(self):
        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")

    def actions(self, records: list[tuple[LearningRecord, Learning]]):
        x: list[datetime] = []
        y: list[int] = []
        count_learning: int = 0
        for record, _ in records:
            # FIXME: check if the record is a learning record.
            count_learning += 1
            x.append(record.time)
            y.append(count_learning)
        plt.plot(mdates.date2num(x), y, color="black", linewidth=1)
        self.plot()

    def cumulative_actions(
        self,
        records: list[tuple[LearningRecord, Learning]],
        lexicons: list[Lexicon],
        point: Callable,
        width: float,
        by_language: bool = False,
    ) -> None:

        data: dict[str | int, dict[datetime, int]]
        size: int

        if by_language:
            learnings = {x[1] for x in records}
            data = {
                x.learning_language.get_code(): defaultdict(int)
                for x in learnings
            }
            size = len(data)
        else:
            size = 20
            data = {index: defaultdict(int) for index in range(size)}

        for learning_record, learning in records:
            if by_language:
                data[learning.learning_language.get_code()][
                    point(learning_record.time)
                ] += 1
            elif learning_record.interval:  # type: ignore
                # FIXME: rewrite interval computing.
                days: float = (
                    learning_record.interval.total_seconds()  # type: ignore
                    / 60
                    / 60
                    / 24
                )
                depth: int = max(0, int(np.log2(days)))
                data[depth + 1 + 2][point(learning_record.time)] += 1
            else:
                data[0 + 2][point(learning_record.time)] += 1

        for lexicon in lexicons:
            if not lexicon.log.records:
                continue
            last_record: LexiconLogRecord = lexicon.log.records[0]
            for lexicon_record in lexicon.log.records:
                if (
                    lexicon_record.answer_type == AnswerType.USER_ANSWER
                    or lexicon_record.answer_type == AnswerType.UNKNOWN
                    and (lexicon_record.time - last_record.time).total_seconds()
                    > 0
                ):
                    if not by_language:
                        if lexicon.is_frequency():
                            data[0][point(lexicon_record.time)] += 1
                        else:
                            data[1][point(lexicon_record.time)] += 1
                last_record = lexicon_record

        keys: set[datetime] = set()
        for i in data:
            keys |= data[i].keys()

        xs: list[datetime] = list(sorted(keys))
        categories: list[str | int]

        if by_language:
            categories = list(data.keys())
        else:
            categories = list(range(size))

        for category in categories:
            for x in xs:
                if x not in data[category]:
                    data[category][x] = 0

        for index, i in enumerate(categories):
            if by_language:
                language = Language.from_code(str(i))
                color = util.get_color(i)
                # color = language.get_color().hex
                label = language.get_name()
            elif i == 0:  # log
                color = "#E8F0F8"
                label = "Checking lexicon"
            elif i == 1:  # log_ex
                color = "#D8E0E8"
                label = "Checking new words"
            else:
                color = DEPTH_COLORS[int(i) + 1 - 2]
                label = f"Learning level {int(i) + 1 - 2}"

            ys: list[float] = []
            for x in xs:
                ys.append(
                    sum(data[categories[y]][x] for y in range(index, size))
                )

            if np.any(ys):
                plt.bar(
                    [mdates.date2num(z) for z in xs],
                    ys,
                    color=color.hex,
                    linewidth=0,
                    width=width,
                    label=label,
                )
        plt.legend()
        self.plot()

    def cumulative_actions_moving(
        self,
        records: list[tuple[LearningRecord, Learning]],
        days: int,
    ):
        day_min = day_start(min(x[0].time for x in records))
        day_max = day_start(max(x[0].time for x in records))

        data: list[int] = [0] * ((day_max - day_min).days + 1)

        for record, _ in records:
            if record.response in [Response.RIGHT, Response.WRONG]:
                data[(day_start(record.time) - day_min).days] += 1

        data_moving: list[float] = [0.0] * len(data)
        for index in range(len(data)):
            data_moving[index] = sum(data[max(0, index - days) : index]) / days

        plt.plot(data_moving)

        self.plot()

    def knowing(self, learnings: list[Learning]):
        records: list[tuple[str, LearningRecord]] = []

        for learning in learnings:
            for record in learning.process.records:
                records.append((learning.learning_language.get_code(), record))

        records = sorted(records, key=lambda x: x[1].time)

        x_list: list[datetime] = [x.time for _, x in records]
        min_x: datetime = min(x_list)
        max_x: datetime = util.day_start(datetime.now())
        days: int = int((max_x - min_x).total_seconds() / 3600 / 24)

        points: list[datetime] = [
            util.day_start(min_x) + timedelta(days=i) for i in range(days + 2)
        ] + [datetime.now()]
        print(f"Construct {days + 2} days...")

        # Mapping: learning id -> last learning record.
        knowledge: dict[str, Knowledge] = {}
        data: dict[str, float] = {}

        xs: list[datetime] = []
        values_map: dict[float, list[float]] = {
            0.1: [],
            0.15: [],
            0.2: [],
            0.25: [],
            0.3: [],
        }
        values_language: dict[str, list[float]] = {
            x.learning_language.get_code(): [] for x in learnings
        }
        values_total = []

        index: int = 0

        for point in tqdm(points):
            if index < len(records):
                while records[index][1].time < point:
                    learn_id, record = records[index]
                    id_ = f"{learn_id}///{record.question_id}"
                    if id_ not in knowledge:
                        knowledge[id_] = Knowledge(record.question_id, [record])
                    else:
                        knowledge[id_].add_record(record)
                    data[id_] = 1.0
                    index += 1
                    if index >= len(records):
                        break
            xs.append(point)

            values_c: dict[float, float] = {
                precision: 0.0 for precision in values_map
            }
            values_l: dict[str, float] = {
                x.learning_language.get_code(): 0.0 for x in learnings
            }
            for id_, word_knowledge in knowledge.items():
                if word_knowledge.is_learning():
                    for coef in values_map:
                        values_c[coef] += max(
                            0.0, (1 - coef) ** word_knowledge.estimate(point)
                        )
                    values_l[id_.split("///")[0]] += max(
                        0.0, 0.8 ** word_knowledge.estimate(point)
                    )
                else:
                    for coef in values_map:
                        values_c[coef] += 0.0
                    values_l[id_.split("///")[0]] += 0.0
            for coef in values_map:
                values_map[coef].append(values_c[coef])
            for id_ in values_language:
                values_language[id_].append(values_l[id_])
            values_total.append(
                len([x for x in knowledge.values() if x.is_learning()])
            )

        values_map_bad = {
            pr: [v1 - v2 for v1, v2 in zip(values_map[pr], values_total)]
            for pr in values_map
        }

        _, ax = plt.subplots()

        plt.plot(
            [mdates.date2num(z) for z in xs],
            values_map_bad[0.2],
            color="black",
            linewidth=1,
        )

        for coef, hatch in (0.1, "/"), (0.2, "///"):
            plt.fill_between(
                [mdates.date2num(z) for z in xs],
                [-x * coef for x in values_total],
                [
                    min(x, -y * 0.2)
                    for x, y in zip(values_map_bad[0.2], values_total)
                ],
                hatch=hatch,
                color="none",
                edgecolor="red",
                linewidth=1,
            )

        # Plot number of all words in the learning process.
        plt.plot(
            [mdates.date2num(z) for z in xs],
            values_total,
            color="#888888",
            linewidth=1,
        )

        total = [0.0] * len(xs)
        index = 0
        for id_, language_data in values_language.items():
            language: Language = Language.from_code(id_)
            color = language.get_random_color()
            color = language.get_color().hex
            title = language.get_name()
            new_total = [x + y for x, y in zip(language_data, total)]
            plt.fill_between(
                [mdates.date2num(z) for z in xs],
                total,
                new_total,
                hatch=HATCHES[index % len(HATCHES)],
                label=title,
                color="white",
                edgecolor=color,
            )
            total = new_total
            index += 1

        handles, labels = ax.get_legend_handles_labels()
        ax.legend(
            reversed(handles),
            reversed(labels),
            title="Language",
            loc="upper left",
        )
        self.plot()

    def history(
        self, learnings: Iterator[Learning], marker_size: float = 0.5
    ) -> None:
        data: dict[datetime, int] = {}
        index: int = 0
        indices: dict[str, int] = {}
        for learning in learnings:
            records = learning.process.records
            for record in records:
                id_: str = f"{learning.id_}:{record.question_id}"
                if id_ not in indices:
                    indices[id_] = index
                    index += 1
                data[record.time] = indices[id_]
        x: list[datetime] = sorted(data.keys())
        y: list[int] = list(map(lambda z: data[z], x))
        plt.plot(
            [mdates.date2num(z) for z in x],
            y,
            "o",
            color="black",
            markersize=marker_size,
        )
        self.plot()

    def next_question_time(self, learnings: Iterator[Learning]):
        data: dict[datetime, float] = {}
        for learning in learnings:
            for word in learning.knowledge:
                record = learning.knowledge[word]
                time = learning.get_next_time(record)
                data[time] = random.random()  # time.hour * 60 + time.minute
        x: list[datetime] = list(sorted(data.keys()))
        y: list[float] = list(map(lambda z: data[z], x))
        plt.plot(
            [mdates.date2num(z) for z in x],
            y,
            "o",
            color="black",
            markersize=0.5,
        )
        self.plot()

    def graph_mistakes(self, learnings: Iterator[Learning]) -> None:
        for learning in learnings:
            records: list[tuple[str, LearningRecord]] = []
            for record in learning.process.records:
                records.append((learning.id_, record))

            size: int = 10
            xs = range(size)
            ys: list[int] = [0] * size
            ns: list[int] = [0] * size
            lasts: dict[str, int] = defaultdict(int)
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
            plt.plot(
                xs,
                [
                    (
                        ns[i] / (ns[i] + ys[i]) * 100
                        if (ns[i] + ys[i] > 0)
                        else 0
                    )
                    for i in range(size)
                ],
            )
        plt.ylim(ymin=0)
        plt.xlim([0, size - 1])
        self.plot()

    def response_time(
        self,
        records: list[tuple[LearningRecord, Learning]],
        steps: int = 5,
        max_: int = 60,
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

        last_record: LearningRecord | None = records[0][0] if records else None

        for record, _ in records:
            if last_record is None:
                last_record = record
                continue
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
