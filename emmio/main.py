import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from logging import info
from pathlib import Path
from typing import Optional

from emmio import util, ui, __main__
from emmio.dictionary import Dictionary, Dictionaries
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.frequency import FrequencyDatabase, FrequencyList
from emmio.graph import Visualizer
from emmio.language import (
    Language,
    construct_language,
    LanguageNotFound,
    RUSSIAN,
)
from emmio.learning.core import Learning, LearningRecord, ResponseType
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.sentence.database import SentenceDatabase
from emmio.teacher import Teacher
from emmio.ui import Logger, set_log, Interface, progress, error
from emmio.user_data import UserData

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

HELP: list[list[str]] = [
    ["help", "print this message"],
    ["exit / quit", "close Emmio"],
    ["learn / <Enter>", "start learning process"],
    ["stat learn", "print learning statistics"],
    ["plot learn [by time] [by depth]", "plot graph of the learning process"],
    ["response time", "show response time graph"],
    ["next question time", "show next question time graph"],
    ["actions [per day]", "show actions graph"],
    ["lexicon", "check lexicons"],
    ["stat lexicon", "print lexicon statistics"],
    ["plot lexicon", "draw lexicon graph"],
]


class Emmio:
    """Emmio entry point."""

    def __init__(self, user_data: UserData, path: Path, interface: Interface):
        self.user_data: UserData = user_data
        self.path: Path = path
        self.interface: Interface = interface

        self.sentence_db: SentenceDatabase = SentenceDatabase(
            path / "sentence.db"
        )
        self.frequency_db: FrequencyDatabase = FrequencyDatabase(
            path / "frequency.db"
        )
        with (path / "config.json").open() as input_file:
            self.config = json.load(input_file)

    def get_dictionaries(self, language: Language) -> list[Dictionary]:
        dictionaries: list[Dictionary] = []

        wiktionary: Dictionary = EnglishWiktionary(Path("cache"), language)
        dictionaries.append(wiktionary)

        return dictionaries

    def run(self):

        print("\nEmmio\n")

        print(
            """
    Press <Enter> or print "learn" to start learning.
    Print "help" to see commands or "exit" to quit.
"""
        )

        while True:
            command: str = input("> ")

            if command in ["q", "quit", "exit"]:
                return

            self.process_command(command)

    def process_command(self, command: str, interactive: bool = True) -> None:

        if command == "help":
            self.interface.table(["Command", "Description"], HELP)

        if not command or command == "learn":
            self.learn()

        if command.startswith("lexicon"):
            self.run_lexicon(command[len("lexicon") :])

        if command == "stat learn":
            self.user_data.get_stat(self.interface)

        if command == "stat lexicon":

            rows = []

            for language in sorted(
                self.user_data.get_lexicon_languages(),
                key=lambda x: -self.user_data.get_lexicon(
                    x
                ).get_last_rate_number(),
            ):
                lexicon: Lexicon = self.user_data.get_lexicon(language)
                now: datetime = datetime.now()
                rate: Optional[float] = lexicon.get_last_rate()
                last_week_precision: int = lexicon.count_unknowns(
                    "log", now - timedelta(days=7), now
                )
                rows.append(
                    [
                        language.get_name(),
                        progress(max(0, 5 - last_week_precision)),
                        f"{abs(rate):.1f}  " + progress(int(rate * 10))
                        if rate is not None
                        else "N/A",
                    ]
                )

            self.interface.table(["Language", "Need", "Rate"], rows)

        if command == "plot lexicon":
            LexiconVisualizer(interactive=interactive).graph_with_matplot(
                [
                    self.user_data.get_lexicon(language)
                    for language in self.user_data.get_lexicon_languages()
                ]
            )

        if command == "svg lexicon":
            LexiconVisualizer(
                first_point=util.year_start,
                next_point=lambda x: x + timedelta(days=365.25),
                impulses=False,
            ).graph_with_svg(
                [
                    self.user_data.get_lexicon(language)
                    for language in self.user_data.get_lexicon_languages()
                ],
                1.5,
            )

        if command == "svg lexicon week":
            LexiconVisualizer().graph_with_svg(
                [
                    self.user_data.get_lexicon(language)
                    for language in self.user_data.get_lexicon_languages()
                ],
            )

        if command == "data":
            for course_id in self.user_data.course_ids:
                ui.log(f"construct data for {course_id}")
                learning: Learning = self.user_data.get_course(course_id)
                self.fill_data(
                    construct_language(learning.subject),
                    self.user_data.get_frequency_list(
                        learning.frequency_list_ids[-1]
                    ),
                )

        if command == "to learn":

            rows = []
            for course_id in self.user_data.course_ids:
                learning = self.user_data.get_course(course_id)

                rows.append([f"== {learning.name} =="])
                for word, knowledge in learning.knowledges.items():
                    if knowledge.get_last_answer() == ResponseType.WRONG:
                        item = self.get_dictionaries(
                            construct_language(learning.subject)
                        )[0].get_item(word)
                        text: Optional[str] = None
                        if item:
                            transcription, text = item.get_short(RUSSIAN)
                            rows.append(
                                [
                                    word,
                                    self.interface.colorize(
                                        transcription, "yellow"
                                    )
                                    + " "
                                    + text,
                                ]
                            )
                        else:
                            rows.append([word])

            self.interface.table(["Word", "Translation"], rows)

        if command == "schedule":
            hours = [0] * 24
            now = datetime.now()
            start = datetime(
                year=now.year, month=now.month, day=now.day, hour=now.hour
            )

            for course_id in self.user_data.course_ids:
                learning: Learning = self.user_data.get_course(course_id)
                for question_id, knowledge in learning.knowledges.items():
                    if knowledge.is_learning():
                        if (
                            start
                            <= knowledge.get_next_time()
                            < start + timedelta(hours=24)
                        ):
                            hours[
                                int(
                                    (
                                        knowledge.get_next_time() - start
                                    ).total_seconds()
                                    // 60
                                    // 60
                                )
                            ] += 1
                        elif knowledge.get_next_time() < now:
                            hours[0] += 1

            print(sum(hours))
            for h in range(24):
                time = start + timedelta(hours=h)
                print(
                    f"{time.day:2} {time.hour:2}:00 {hours[h]:2} "
                    f"{progress(hours[h])}"
                )

        if command in Visualizer.get_commands():
            ratios = 0
            learning_words = 0
            records: list[LearningRecord] = []
            knowledges = {}
            for course_id in self.user_data.course_ids:
                learning: Learning = self.user_data.get_course(course_id)
                if not learning.is_learning:
                    continue
                ratios += learning.ratio
                learning_words += learning.learning()
                records += learning.records
                knowledges |= learning.knowledges

            visualizer = Visualizer(interactive=interactive)
            records = sorted(records, key=lambda x: x.time)

            lexicons = [
                self.user_data.get_lexicon(language)
                for language in self.user_data.get_lexicon_languages()
            ]
            visualizer.process_command(command, records, knowledges, lexicons)

    def run_lexicon(self, code: str) -> None:
        """Check all user lexicons."""

        if code.endswith(" ra"):
            language_code = code[1:3]
            language = construct_language(language_code)
            lexicon = self.user_data.get_lexicon(language)
            lexicon.check(
                self.interface,
                self.user_data.get_frequency_list_for_lexicon(language),
                None,
                Dictionaries(self.get_dictionaries(language)),
                "most frequent",
                False,
                False,
                None,
                learning=self.user_data.get_course(f"ru_{language_code}"),
            )
            return

        priority_path: Path = self.path / "priority"
        priority_path.mkdir(parents=True, exist_ok=True)

        if code:
            languages = [construct_language(code[1:])]
        else:
            languages = sorted(
                self.user_data.get_lexicon_languages(),
                key=lambda x: -self.user_data.get_lexicon(
                    x
                ).get_last_rate_number(),
            )

        for language in languages:
            lexicon: Lexicon = self.user_data.get_lexicon(language)
            now: datetime = datetime.now()
            need: int = 5 - lexicon.count_unknowns(
                "log", now - timedelta(days=7), now
            )
            need = max(need, 100 - lexicon.count_unknowns("log"))
            if need <= 0:
                continue

            self.interface.header(f"Lexicon for {language.get_name()}")

            lexicon.check(
                self.interface,
                self.user_data.get_frequency_list_for_lexicon(language),
                None,
                Dictionaries(self.get_dictionaries(language)),
                "frequency",
                False,
                False,
                need,
            )
            break

    def learn(self) -> None:
        sorted_ids: list[str] = sorted(
            self.user_data.course_ids,
            key=lambda x: -self.user_data.get_course(x).to_repeat(),
        )
        for course_id in sorted_ids:
            learning: Learning = self.user_data.get_course(course_id)
            if not learning.is_learning:
                continue

            lexicon: Optional[Lexicon]

            try:
                lexicon = self.user_data.get_lexicon(
                    construct_language(learning.subject)
                )
            except LanguageNotFound:
                lexicon = None

            for frequency_list_id in learning.frequency_list_ids:
                frequency_list: Optional[
                    FrequencyList
                ] = self.user_data.get_frequency_list(frequency_list_id)

                if frequency_list is None:
                    error(
                        f"frequency list for {frequency_list_id} was not "
                        f"constructed"
                    )
                    return

                if frequency_list.update and self.frequency_db.has_table(
                    frequency_list_id
                ):
                    self.frequency_db.drop_table(frequency_list_id)

                if not self.frequency_db.has_table(frequency_list_id):
                    info(f"adding frequency database table {frequency_list_id}")
                    self.frequency_db.add_table(
                        frequency_list_id, frequency_list
                    )

            if learning.to_repeat() > 0:
                self.interface.header(f"Repeat learned for {learning.name}")
                teacher: Teacher = Teacher(
                    Path("cache"),
                    self.interface,
                    self.user_data,
                    self.sentence_db,
                    self.frequency_db,
                    learning,
                    lexicon,
                    get_dictionaries=self.get_dictionaries,
                )
                if not teacher.repeat():
                    return

        sorted_ids = sorted(
            self.user_data.course_ids,
            key=lambda x: (
                0
                if not self.user_data.get_course(x).ratio
                else self.user_data.get_course(x).learning()
                / self.user_data.get_course(x).ratio
            ),
        )
        for course_id in sorted_ids:
            learning = self.user_data.get_course(course_id)
            lexicon: Lexicon = self.user_data.get_lexicon(
                construct_language(learning.subject)
            )
            if learning.ratio > learning.new_today():
                self.interface.header(
                    f"Learn new and repeat for {learning.name}"
                )
                learner = Teacher(
                    Path("cache"),
                    self.interface,
                    self.user_data,
                    self.sentence_db,
                    self.frequency_db,
                    learning,
                    lexicon,
                    get_dictionaries=self.get_dictionaries,
                )
                proceed = learner.start()
                if not proceed:
                    return

        print()

        now: datetime = datetime.now()
        time_to_repetition: timedelta = (
            min(x.get_nearest() for x in self.user_data.courses.values()) - now
        )
        time_to_new: timedelta = util.day_end(now) - now
        if time_to_repetition < time_to_new:
            print(f"    Repetition in {time_to_repetition}.")
        else:
            print(f"    New question in {time_to_new}.")
        print()


def main() -> None:
    """Entry point."""
    set_log(Logger)

    data_path: Path = Path(sys.argv[1])
    user_id: str = sys.argv[2]
    interface: Interface = ui.RichInterface()

    interface.run()

    emmio: Emmio = Emmio(
        UserData.from_directory(data_path, user_id),
        data_path,
        interface,
    )

    if len(sys.argv) > 3:
        command = " ".join(sys.argv[3:])
        emmio.process_command(command, interactive=False)
    else:
        emmio.run()

    interface.stop()


if __name__ == "__main__":
    __main__.main()
