import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import coloredlogs

from emmio import util
from emmio.analyze import Analysis
from emmio.data import Data
from emmio.graph import Visualizer
from emmio.language import Language
from emmio.learn.core import Learning, LearningRecord, Response
from emmio.learn.visualizer import LearningVisualizer
from emmio.lexicon.core import Lexicon
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.learn.teacher import Teacher
from emmio.listen.listener import Listener
from emmio.read.core import Read
from emmio.ui import Interface, progress
from emmio.user.data import UserData, Record, Session

LEXICON_HELP: str = """
<y> or <Enter>  I know at least one meaning of the word
<n>             I don’t know any of meanings of the word
<s>             I know at least one meanings of the word and I’m sure I
                will not forget it, skip this word in the future
<b>             I don’t know any of meanings of the word, but it is a proper
                name too
<->             the word doesn’t exist or is a proper name

<q>             exit
"""


class ArgumentParser(argparse.ArgumentParser):
    def help(self, _):
        self.print_help(sys.stdout)


class Emmio:
    """Emmio entry point."""

    def __init__(
        self, path: Path, interface: Interface, data: Data, user_id: str
    ) -> None:
        self.path: Path = path
        self.interface: Interface = interface
        self.data: Data = data

        if not data.has_user(user_id):
            answer: str = self.interface.choice(
                ["Yes", "No"],
                f"User with id `{user_id}` does not exist. Do you want to "
                "create new user?",
            )
            if answer == "yes":
                user_name = self.interface.input("Enter user name: ")
            else:
                return
            data.create_user(user_id, user_name)

        self.user_data: UserData = data.users_data[user_id]
        self.user_id: str = user_id

    def run(self):
        print("\nEmmio\n")

        print(
            """
    Press <Enter> or print "learn" to start learning.
    Print "help" to see commands or "exit" to quit.
"""
        )

        while True:
            command: str = input("Emmio > ")

            if command in ["q", "quit", "exit"]:
                return

            # try:
            self.process_command(command)
            # except Exception:
            #     logging.error("There was an error in command processing.")

    def process_command(self, command: str, interactive: bool = True) -> None:
        data: Data = self.data

        parser: ArgumentParser = ArgumentParser(
            exit_on_error=False, add_help=False
        )
        subparsers = parser.add_subparsers(dest="command")

        help_parser = subparsers.add_parser("help", help="print help message")
        help_parser.add_argument("subcommand", nargs="?")

        learn_parser = subparsers.add_parser("learn", help="learn topics")
        learn_parser.add_argument("topic", nargs="?")

        lexicon_parser = subparsers.add_parser("lexicon", help="check lexicon")
        lexicon_parser.add_argument("language", nargs="?")

        read_parser = subparsers.add_parser("read", help="read text")
        read_parser.add_argument("id")

        stat_parser = subparsers.add_parser("stat", help="show statistics")
        stat_parser.add_argument(
            "process",
            choices=["actions", "learn", "lexicon"],
            default="learn",
            help="what print statistics for",
        )

        plot_parser = subparsers.add_parser("plot", help="plot a graph")
        plot_subparsers = plot_parser.add_subparsers(dest="process")

        plot_lexicon_parser = plot_subparsers.add_parser(
            "lexicon",
            help="plot lexicon rate",
            description="""
                Plot lexicon rate. Lexicon rate is `-log_2(x)`, where `x` is a 
                number of words the user don't know in a random text.
            """,
        )
        plot_lexicon_parser.add_argument(
            "--show-text",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="show language names at the right side of the graphs",
        )
        plot_lexicon_parser.add_argument(
            "--interval",
            default="year",
            choices=["day", "week", "month", "year"],
            help="interval of X axis",
        )
        plot_lexicon_parser.add_argument(
            "--margin", default=0.0, type=float, help="minimum Y value"
        )
        plot_lexicon_parser.add_argument(
            "--svg", action=argparse.BooleanOptionalAction
        )
        plot_lexicon_parser.add_argument("--languages", type=str)

        plot_learn_parser = plot_subparsers.add_parser(
            "learn", help="plot learning questions"
        )
        plot_learn_parser.add_argument(
            "--interactive",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="show interactive Matplotlib window",
        )
        plot_learn_parser.add_argument(
            "--actions",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="use number of actions for the X axis instead of time",
        )
        plot_learn_parser.add_argument(
            "--depth",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="group by question depth instead of learning topic",
        )
        plot_learn_parser.add_argument(
            "--pressure",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="count pressure instead of question number",
        )

        plot_actions_parser = plot_subparsers.add_parser(
            "actions", help="plot number of user actions"
        )
        plot_actions_parser.add_argument("--interval", default="year")
        plot_actions_parser.add_argument(
            "--depth",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="group by question depth instead of learning topic",
        )
        plot_actions_parser.add_argument(
            "--moving",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="use moving average",
        )

        plot_knowing_parser = plot_subparsers.add_parser(
            "knowing", help="plot cumulative amount of learned questions"
        )

        plot_schedule_parser = plot_subparsers.add_parser(
            "schedule", help="plot scheduled question time"
        )

        plot_history_parser = plot_subparsers.add_parser(
            "history", help="plot history"
        )
        plot_history_parser.add_argument(
            "--size", "-s", help="marker size", type=float
        )

        audio_parser = subparsers.add_parser(
            "audio", aliases=["listen", "play"], help="play audio learning"
        )
        audio_parser.add_argument("id", help="listening process identifier")
        audio_parser.add_argument(
            "--start-from",
            help="start from the word in the list with that index",
            type=int,
            default=0,
        )
        audio_parser.add_argument("--repeat", type=int, default=1)

        analyze_parser = subparsers.add_parser("analyze")
        analyze_parser.add_argument("language")

        subparsers.add_parser("debug")

        if command:
            try:
                arguments = parser.parse_args(command.split(" "))
            except argparse.ArgumentError:
                arguments = argparse.Namespace(command="no")
                pass
            except SystemExit:
                arguments = argparse.Namespace(command="no")
                pass
        else:
            arguments = argparse.Namespace(command="learn", topic=None)

        if arguments.command == "help":
            if arguments.subcommand == "learn":
                learn_parser.print_help()
            else:
                parser.print_help()

        if arguments.command == "debug":
            self.debug()

        if arguments.command == "analyze":
            analysis = Analysis(self.data, self.user_data)
            analysis.analyze(
                Language.from_code(arguments.language),
                self.data.get_frequency_list("hy_wortschatz_community_2017"),
            )

        if arguments.command == "read":
            read_process: Read = self.user_data.get_read_process(arguments.id)
            self.read(read_process)

        if arguments.command == "learn":
            # We cannot use iterators here!
            learnings: list[Learning]
            if arguments.topic:
                learnings = [
                    self.data.get_learning(self.user_id, arguments.topic)
                ]
            else:
                learnings = list(self.data.get_active_learnings(self.user_id))

            self.learn(learnings)

        if arguments.command == "lexicon":
            lexicons = [
                x
                for x in self.user_data.get_lexicons()
                if x.get_precision_per_week()
                and (
                    not arguments.language
                    or x.language.get_code() in arguments.language
                )
            ]
            self.run_lexicon(
                sorted(lexicons, key=lambda x: -x.get_last_rate_number())
            )

        if command.startswith("read "):
            _, request = command.split(" ")
            read_processes = self.data.get_read_processes(self.user_id)
            for id_, read in read_processes.items():
                if id_.startswith(request):
                    self.read(read)
                    break

        if arguments.command == "stat":
            if arguments.process == "actions":
                stat = defaultdict(int)
                for learning in self.data.get_learnings(self.user_id):
                    stat[learning.learning_language] += learning.get_actions()
                self.interface.table(
                    ["Language", "Actions"],
                    [
                        [x.get_name(), str(y)]
                        for x, y in sorted(stat.items(), key=lambda x: -x[1])
                    ],
                )

            elif arguments.process == "learn":
                self.data.print_learning_statistics(
                    self.interface, self.user_id
                )

            elif arguments.process == "lexicon":
                rows = []

                lexicons: list[Lexicon] = []
                for language, language_lexicons in data.get_frequency_lexicons(
                    self.user_id
                ).items():
                    lexicons_to_check = [
                        x
                        for x in language_lexicons
                        if x.get_precision_per_week()
                    ]
                    if len(lexicons_to_check) == 1:
                        lexicons.append(lexicons_to_check[0])
                    else:
                        logging.fatal(
                            f"More than one lexicon to check for {language}."
                        )

                for lexicon in sorted(
                    lexicons, key=lambda x: -x.get_last_rate_number()
                ):
                    now: datetime = datetime.now()
                    rate: float | None = lexicon.get_last_rate()
                    rate_year_before: float | None = lexicon.get_last_rate(
                        before=now - timedelta(days=365.25)
                    )
                    last_week_precision: int = lexicon.count_unknowns(
                        now - timedelta(days=7), now
                    )
                    need: int = max(
                        0,
                        lexicon.get_precision_per_week() - last_week_precision,
                    )
                    change = (
                        abs(rate) - abs(rate_year_before)
                        if rate_year_before is not None and rate is not None
                        else 0
                    )
                    if change >= 0.1:
                        change = f"[green]▲ +{change:.1f}"
                    elif change <= -0.1:
                        change = f"[red]▼ {change:.1f}"
                    else:
                        change = ""
                    if not rate:
                        continue
                    rows.append(
                        [
                            lexicon.language.get_name(),
                            progress(need),
                            f"{abs(rate):.1f}  " + progress(int(rate * 10))
                            if rate is not None
                            else "N/A",
                            change,
                        ]
                    )

                self.interface.table(
                    ["Language", "Need", "Rate", "Year change"], rows
                )

        if arguments.command == "plot":
            if arguments.process == "lexicon":
                self.plot_lexicon(
                    arguments.interval,
                    interactive,
                    arguments.languages,
                    arguments.svg,
                    arguments.margin,
                    arguments.show_text,
                )
            elif arguments.process == "learn":
                records: list[tuple[LearningRecord, Learning]] = []
                for learning in self.user_data.get_active_learnings():
                    records += [(x, learning) for x in learning.process.records]
                records = sorted(records, key=lambda x: x[0].time)
                LearningVisualizer(
                    records,
                    interactive=arguments.interactive,
                    is_time=not arguments.actions,
                    count_by_depth=arguments.pressure,
                    by_language=not arguments.depth,
                ).draw()
            elif arguments.process == "knowing":  # `plot knowing`
                Visualizer().knowing(
                    list(self.user_data.get_active_learnings())
                )
            elif arguments.process == "schedule":  # `plot schedule`
                Visualizer().next_question_time(
                    self.user_data.get_active_learnings()
                )
            elif arguments.process == "history":  # `plot history`
                Visualizer().history(
                    self.user_data.get_active_learnings(), arguments.size
                )
            elif arguments.process == "actions":  # `plot actions`
                records: list[tuple[LearningRecord, Learning]] = []
                for learning in self.user_data.get_active_learnings():
                    records += [(x, learning) for x in learning.process.records]
                records = sorted(records, key=lambda x: x[0].time)

                if arguments.moving:
                    match arguments.interval:
                        case "week":
                            days = 7
                        case "month":
                            days = 30
                        case "year":
                            days = 365
                        case _:
                            days = 10

                    Visualizer().cumulative_actions_moving(records, days=days)
                else:

                    def locator(x):
                        return datetime(day=x.day, month=x.month, year=x.year)

                    days = 1

                    if arguments.interval == "week":
                        locator, days = util.first_day_of_week, 7
                    elif arguments.interval == "month":
                        locator, days = util.first_day_of_month, 31
                    elif arguments.interval == "year":
                        locator, days = util.year_start, 365 * 0.6

                    Visualizer().cumulative_actions(
                        records,
                        list(self.user_data.get_lexicons()),
                        point=locator,
                        width=days,
                        by_language=not arguments.depth,
                    )

        if arguments.command == "audio":
            self.listen(arguments.id, arguments.start_from, arguments.repeat)

        if command == "data":
            for learning in self.user_data.get_active_learnings():
                logging.info(f"construct data for {learning.config.name}")
                self.fill_data(
                    learning.learning_language,
                    data.get_frequency_list(learning.frequency_list_ids[-1]),
                )

        if command == "to learn":
            rows = []
            for learning in self.user_data.get_active_learnings():
                rows.append([f"== {learning.config.name} =="])
                for word, knowledge in learning.knowledge.items():
                    if knowledge.get_last_response() != Response.WRONG:
                        continue
                    items = self.data.dictionaries.get_dictionaries(
                        learning.config.dictionaries
                    ).get_items(word, learning.learning_language)

                    if not items:
                        rows.append([word])
                        continue

                    transcription, text = items[0].get_short(
                        learning.base_languages[0]
                    )
                    if transcription:
                        text = f"[yellow]{transcription} [black]{text}"
                    rows.append([word, text])

            self.interface.table(["Word", "Translation"], rows)

        if command == "schedule":
            hours = [0] * 24
            now = datetime.now()
            start = datetime(
                year=now.year, month=now.month, day=now.day, hour=now.hour
            )

            rows = []
            for learning in self.user_data.get_active_learnings():
                for question_id, knowledge in learning.knowledge.items():
                    if not knowledge.is_learning():
                        continue
                    if (
                        start
                        <= learning.get_next_time(knowledge)
                        < start + timedelta(hours=24)
                    ):
                        seconds = learning.get_next_time(knowledge) - start
                        hours[int(seconds.total_seconds() // 60 // 60)] += 1
                    elif learning.get_next_time(knowledge) < now:
                        hours[0] += 1

            print(sum(hours))
            for hour in range(24):
                time: datetime = start + timedelta(hours=hour)
                rows.append(
                    [
                        f"{time.day:2}",
                        f"{time.hour:2}:00",
                        f"{hours[hour]:2} {progress(hours[hour])}",
                    ]
                )
            self.interface.table(["Day", "Time", "To repeat"], rows)

        if Visualizer.check_command(command):
            records: list[tuple[LearningRecord, Learning]] = []
            knowledge = {}
            learnings: list[Learning] = list(
                self.user_data.get_active_learnings()
            )

            for learning in learnings:
                records += [(x, learning) for x in learning.process.records]
                knowledge |= learning.knowledge

            visualizer: Visualizer = Visualizer(interactive=interactive)
            records = sorted(records, key=lambda x: x[0].time)

            lexicons: list[Lexicon] = [
                self.user_data.get_lexicon(learning.learning_language)
                for learning in self.user_data.get_active_learnings()
            ]
            visualizer.process_command(
                command, records, knowledge, learnings, lexicons
            )

    def run_lexicon(self, lexicons: list[Lexicon]) -> None:
        """Check user vocabulary."""

        for lexicon in lexicons:
            language: Language = lexicon.language
            now: datetime = datetime.now()
            need: int = 5 - lexicon.count_unknowns(now - timedelta(days=7), now)
            need = max(need, 101 - lexicon.count_unknowns())
            if need <= 0:
                continue

            self.interface.header(f"Lexicon for {language.get_name()}")

            lexicon.check(
                self.interface,
                self.data.get_frequency_list(lexicon.config.frequency_list),
                None,
                self.data.get_dictionaries(lexicon.config.dictionaries),
                self.data.get_sentences_collection(lexicon.config.sentences),
                "frequency",
                False,
                False,
                need,
            )
            break

    def debug(self):
        result: list[
            tuple[Session, list[Record]]
        ] = self.user_data.get_sessions_and_records()

        data: list[float] = []

        seconds: int = 0
        for session, records in result:
            session: Session
            records: list[Record]
            for index, record in enumerate(records):
                span: float
                if index == 0:
                    span = (
                        record.get_time() - session.get_start()
                    ).total_seconds()
                else:
                    span = (
                        record.get_time() - records[index - 1].get_time()
                    ).total_seconds()
                data.append(span)
                seconds += span

        print(f"Total time: {seconds / 60 / 60:.2f}")

        from matplotlib import pyplot as plt

        plt.xlim([0, 60])
        plt.hist([x for x in data if x <= 60], bins=170)
        plt.show()

    def read(self, read: Read):
        coloredlogs.install(
            level=logging.ERROR,
            fmt="%(message)s",
            level_styles=dict(
                info=dict(color="yellow"), error=dict(color="red")
            ),
        )
        read.read(
            self.interface,
            self.user_data,
            self.data.get_dictionaries(read.config.dictionaries),
            self.data.get_text(read.config.text),
        )

    def learn(self, learnings: list[Learning]) -> None:
        while True:
            learnings = sorted(learnings, key=lambda x: x.compare_by_old())
            learning: Learning = learnings[0]
            if learning.count_questions_to_repeat() > 0:
                teacher: Teacher = Teacher(
                    self.interface,
                    self.data,
                    self.user_data,
                    learning,
                    stop_after_answer=True,
                )
                self.interface.box(
                    "Repeat questions for "
                    + learning.learning_language.get_name()
                )
                do_continue: bool = teacher.repeat(max_actions=10)
                self.data.print_learning_statistics(
                    self.interface, self.user_id
                )
                reply: str = self.interface.choice(["Yes", "No"], "Continue?")
                if reply == "no" or not do_continue:
                    return
            else:
                learnings = sorted(learnings, key=lambda x: x.compare_by_new())
                learning: Learning = learnings[0]
                if learning.count_questions_to_add() > 0:
                    teacher: Teacher = Teacher(
                        self.interface,
                        self.data,
                        self.user_data,
                        learning,
                        stop_after_answer=True,
                    )
                    self.interface.box(
                        "Learn new words for "
                        + learning.learning_language.get_name()
                    )
                    do_continue: bool = teacher.learn_new()
                    self.interface.box("All new words added")
                    self.data.print_learning_statistics(
                        self.interface, self.user_id
                    )
                    reply: str = self.interface.choice(
                        ["Yes", "No"], "Continue?"
                    )
                    if reply == "no" or not do_continue:
                        return
                else:
                    break

        print()

        now: datetime = datetime.now()
        time_to_repetition: timedelta = (
            min(
                x.get_nearest()
                for x in self.user_data.learnings.learnings.values()
                if x.config.is_active and x.get_nearest()
            )
            - now
        )
        time_to_new: timedelta = util.day_end(now) - now
        if time_to_repetition < time_to_new:
            print(f"    Repetition in {time_to_repetition}.")
        else:
            print(f"    New question in {time_to_new}.")
        print()

    def listen(self, listening_id: str, start_from: int, repeat: int) -> None:
        Listener(
            self.user_data.get_listening(listening_id),
            self.data,
            self.user_data,
        ).listen(start_from, repeat)

    def plot_lexicon(
        self, interval, interactive, languages, svg, margin, show_text
    ):
        first_point = util.year_start
        next_point = lambda x: x + timedelta(days=365.25)
        if interval == "week":
            first_point = util.first_day_of_week
            next_point = lambda x: x + timedelta(days=7)
        if interval == "month":
            first_point = util.first_day_of_month
            next_point = util.plus_month

        lexicons: dict[
            Language, list[Lexicon]
        ] = self.user_data.get_frequency_lexicons(languages)
        lexicon_visualizer = LexiconVisualizer(
            interactive=interactive,
            first_point=first_point,
            next_point=next_point,
            impulses=False,
        )
        if svg:
            lexicon_visualizer.graph_with_svg(lexicons, margin=margin)
        else:
            lexicon_visualizer.graph_with_matplot(
                lexicons,
                show_text=show_text,
                margin=margin,
            )
