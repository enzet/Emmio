from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from matplotlib import pyplot as plt, dates as mdates, transforms as mtransforms

from emmio.learning.core import LearningRecord, Knowledge

DEPTH_COLORS_BLACK_AND_WHITE: list[str] = ["#000000"] + [
    "#" + f"{hex(int(256 - 256 / 1.5 ** x))[2:]:2}".replace(" ", "0") * 3
    for x in range(20)
]
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
    show_not_learning: bool = False
    color_mode: str = "depth_colors"

    interactive: bool = True

    def draw(self):
        """Show depth graph."""
        data = defaultdict(float)
        x = []
        y = {}

        max_depth: int = 0

        knowledges = {}

        def compute_data_id() -> str:
            return (
                f"{get_depth(knowledges[record.question_id].interval):05},"
                f"{knowledges[record.question_id].get_answers_number():05}"
            )

        def parse_data_id() -> list[int]:
            return [int(z) for z in id_.split(",")]

        count = 0

        # Compute data for the plot.

        for record in self.records:
            if record.question_id in knowledges:
                data[compute_data_id()] -= (
                    1 / (2 ** knowledges[record.question_id].get_depth())
                    if self.count_by_depth
                    else 1
                )
            if not record.is_learning():
                if self.show_not_learning:
                    data["00010,00001"] += 1
                continue
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
                data[compute_data_id()] += (
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

        # Plot data.

        for id_ in sorted(data.keys()):
            depth, returns = parse_data_id()
            max_depth = max(max_depth, depth)

            color: str
            if self.color_mode == "return_colors":
                number: int = max(0, 255 - returns * 0 - depth * 10)
                color = (
                    f"#{hex(number)[2:]:>02}"
                    f"{hex(number)[2:]:>02}"
                    f"{hex(number)[2:]:>02}"
                )
            else:  # Depth colors.
                color = DEPTH_COLORS[depth + 1]

            plt.fill_between(
                x, [0] * (len(x) - len(y[id_])) + y[id_], color=color
            )

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

            for depth in range(max_depth + 1):
                for j in range(10, 0, -1):
                    id_: str = f"{depth:05},{j:05}"
                    if id_ in y:
                        plt.text(
                            x[-1],
                            y[id_][-1],
                            f"{2 ** depth} days",
                            transform=trans_offset,
                        )
                        break

        if self.interactive:
            plt.show()
        else:
            plt.savefig("out/graph.svg")
