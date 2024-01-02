from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
from matplotlib import pyplot as plt, dates as mdates, transforms as mtransforms

from emmio.learn.core import LearningRecord, Knowledge, Learning

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

    return max(0, int(np.log2(seconds / 60.0 / 60.0 / 24.0)))


@dataclass
class LearningVisualizer:
    # User responses.
    records: list[tuple[LearningRecord, Learning]]

    # If true, use time as x-axis, otherwise use actions count.
    is_time: bool = False

    # Depth labels.
    show_text: bool = False

    by_language: bool = False
    count_by_depth: bool = False
    show_not_learning: bool = False
    color_mode: str = "depth_colors"

    # Distinguish not only depth level, but also the total number of answers.
    use_subtypes: bool = False

    graph_mode: str = "fill_between"

    interactive: bool = True

    def draw(self):
        """Show depth graph."""
        data = defaultdict(float)
        x = []
        y = {}

        max_depth: int = 0

        knowledges = {}

        def compute_data_id() -> str | int:
            if self.by_language:
                return learning.learning_language.get_code()
            if self.use_subtypes:
                return (
                    f"{get_depth(knowledges[record.question_id].interval):05},"
                    f"{knowledges[record.question_id].count_responses():05}"
                )
            return get_depth(knowledges[record.question_id].interval)

        def parse_data_id() -> list[int]:
            return [int(z) for z in id_.split(",")]

        count = 0

        # Compute data for the plot.

        for record, learning in self.records:
            if record.question_id in knowledges:
                data[compute_data_id()] -= (
                    1 / (2 ** knowledges[record.question_id].get_depth())
                    if self.count_by_depth
                    else 1
                )
            if (
                record.question_id in knowledges
                and not knowledges[record.question_id].is_learning()
            ):
                if self.show_not_learning:
                    if self.use_subtypes:
                        data["00010,00001"] += 1
                    else:
                        data[10] += 1
                continue
            else:
                last_answers: list[LearningRecord] = (
                    knowledges[record.question_id].records
                    if record.question_id in knowledges
                    else []
                )
                knowledges[record.question_id] = Knowledge(
                    record.question_id,
                    last_answers + [record],
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
            if not self.by_language:
                if self.use_subtypes:
                    depth, returns = parse_data_id()
                else:
                    depth, returns = id_, 1
                max_depth = max(max_depth, depth)

            color: str
            if self.by_language:
                color = "#" + str(hex(abs(hash(id_))))[2:8]
            elif self.color_mode == "return_colors":
                number: int = max(0, 255 - returns * 0 - depth * 10)
                color = (
                    f"#{hex(number)[2:]:>02}"
                    f"{hex(number)[2:]:>02}"
                    f"{hex(number)[2:]:>02}"
                )
            else:  # Depth colors.
                color = DEPTH_COLORS[depth + 1]

            label = None
            if self.by_language:
                label = id_

            if self.graph_mode == "fill_between":
                plt.fill_between(
                    x,
                    [0] * (len(x) - len(y[id_])) + y[id_],
                    color=color,
                    label=label,
                )
            else:  # lines
                plt.plot(
                    x,
                    [0] * (len(x) - len(y[id_])) + y[id_],
                    color=color,
                    linewidth=0.5,
                    label=label,
                )

        plt.title("Question depth")
        plt.xlabel("Time" if self.is_time else "Actions")
        plt.ylabel("Questions")
        if self.by_language:
            plt.legend(loc="upper left")

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
