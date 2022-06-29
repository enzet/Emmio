from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from matplotlib import pyplot as plt, dates as mdates, transforms as mtransforms

from emmio.learning.core import LearningRecord, Knowledge

DEPTH_COLORS: list[str] = [
    "#CCCCCC",
    "#b7c183", "#74c183", "#3e8a83", "#3e5583",
    "#400083", "#380073", "#300063", "#280053",
    "#200043", "#180033", "#100023", "#080013",
    "#000003", "#000000", "#000000", "#000000",
    "#000000", "#000000", "#000000", "#000000",
]  # fmt: skip


def get_depth(interval: timedelta) -> int:
    if not (seconds := interval.total_seconds()):
        return 0

    return int(np.log2(seconds / 60.0 / 60.0 / 24.0))


@dataclass
class LearningVisualizer:

    # User responses.
    records: list[LearningRecord]

    # If true, use time as x-axis, otherwise use actions count.
    is_time: bool = False

    # Depth labels.
    show_text: bool = False

    count_by_depth: bool = False
    interactive: bool = True

    def draw(self):
        """Show depth graph."""
        data = defaultdict(float)
        y = {}
        x = []

        knowledges = {}

        def idn():
            return (
                f"{get_depth(knowledges[record.question_id].interval):05},"
                f"{knowledges[record.question_id].get_answers_number():05}"
            )

        count = 0

        for index, record in enumerate(self.records):
            if record.question_id in knowledges:
                data[idn()] -= (
                    1 / (2 ** knowledges[record.question_id].get_depth())
                    if self.count_by_depth
                    else 1
                )
            if not record.is_learning():
                continue
                data["00010,00001"] += 1
            else:
                last_answers = (
                    knowledges[record.question_id].responses
                    if record.question_id in knowledges
                    else []
                )
                knowledges[record.question_id] = Knowledge(
                    record.question_id,
                    last_answers + [record.answer],
                    record.time,
                    record.interval,
                )
                data[idn()] += (
                    1 / (2 ** knowledges[record.question_id].get_depth())
                    if self.count_by_depth
                    else 1
                )
            x.append(record.time if self.is_time else count)
            count += 1
            s = 0
            for i in reversed(sorted(data.keys())):
                s += data[i]
                if i not in y:
                    y[i] = []
                y[i].append(s)

        fig, ax = plt.subplots()

        if self.is_time:
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
            color = DEPTH_COLORS[depth + 1]
            plt.fill_between(x, [0] * (len(x) - len(y[i])) + y[i], color=color)

        plt.title("Question depth")
        plt.xlabel("Time" if self.is_time else "Actions")
        plt.ylabel("Questions")
        if not self.is_time:
            plt.xlim(xmin=0)
        plt.ylim(ymin=0)

        if self.show_text:
            trans_offset = mtransforms.offset_copy(
                ax.transData, fig=fig, x=0.1, y=0
            )

            for i in range(7):
                for j in range(10, 0, -1):
                    if f"{i:05},{j:05}" in y:
                        plt.text(
                            x[-1],
                            y[f"{i:05},{j:05}"][-1],
                            f"{2 ** i} days",
                            transform=trans_offset,
                        )
                        break

        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")
