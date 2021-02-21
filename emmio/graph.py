import random
from typing import Dict, List, Optional, Set

from datetime import datetime, timedelta

from iso639 import languages
from matplotlib import pyplot as plt
import matplotlib.dates as mdates
import matplotlib.transforms as mtransforms

from emmio.learning import Record, Knowledge, ResponseType

colors = [
    "#CCCCCC",  # "#ff4444", "#ff8866", "#ffc183",
    "#b7c183", "#74c183", "#3e8a83", "#3e5583",
    "#3e0083", "#380073", "#300063", "#280053",
    "#200043", "#180033", "#100023", "#080013",
    "#000003", "#000000", "#000000", "#000000",
]


class Visualizer:
    def __init__(self):
        pass

    @staticmethod
    def get_commands() -> Set[str]:
        return {
            "depth", "depth by time", "graph 2", "actions", "actions per day",
            "response time", "next question time"}

    def process_command(self, command, records, knowledges) -> bool:
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
            self, records: List[Record], is_time: bool = False,
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
            return f"{knowledges[record.question_id].get_depth()}," \
                   f"{knowledges[record.question_id].get_answers_number()}"

        count = 0

        for index, record in enumerate(records):  # type: (int, Record)
            if record.interval.total_seconds() == 0:
                continue
            if record.question_id in knowledges:
                data[idn(record)] -= 1
                # / (2 ** knowledges[record.question_id].get_depth())
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
            # f"#{hex(number)[2:]:>02}{hex(number)[2:]:>02}{hex(number)[2:]:>02}"
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

    def actions(self, records: List[Record]):
        x = []
        count: int = 0
        for record in records:  # type: Record
            count += 1
            x.append(record.time)
        plt.plot(sorted(x), range(len(x)), color="black", linewidth=1)
        plt.show()

    def cumulative_actions(self, records: List[Record]):
        data = {}
        for record in records:  # type: Record
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

    def graph_2(self, records: List[Record]):
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

    def next_question_time(self, last_records: Dict[str, Knowledge]):
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
            records: List[Record], steps: int = 10,
            max_: int = 60) -> None:
        """
        Draw user response time histogram.

        :param records: user response records
        :param steps: number of histogram steps per second
        :param max_: maximum number of seconds to show
        """
        x: List[float] = [time / steps for time in range(0, max_ * steps + 1)]
        y_y: List[float] = [0.0] * (max_ * steps + 1)
        y_n: List[float] = [0.0] * (max_ * steps + 1)

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

    @staticmethod
    def graph_lexicon(lexicons: List, show_text: bool = False):
        from matplotlib import pyplot as plt
        import matplotlib.dates as mdates

        fig, ax = plt.subplots()
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(
            mdates.ConciseDateFormatter(locator))
        for lexicon in lexicons:
            stat = lexicon.construct_precise()
            language_name = languages.get(part1=lexicon.language).name
            plt.plot(
                stat.keys(), stat.values(),
                label=language_name, linewidth=1)
            trans_offset = mtransforms.offset_copy(
                ax.transData, fig=fig, x=0.1, y=0)
            if show_text:
                plt.text(
                    list(stat.keys())[-1], list(stat.values())[-1],
                    language_name, transform=trans_offset)
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        plt.ylim(ymin=0)
        plt.tight_layout()
        plt.show()
