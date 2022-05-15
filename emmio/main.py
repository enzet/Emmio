import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from emmio import util, ui
from emmio.dictionary import Dictionary
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.frequency import FrequencyDatabase, FrequencyList
from emmio.graph import Visualizer, LexiconVisualizer
from emmio.language import Language, construct_language
from emmio.learning import Learning, Record
from emmio.lexicon import Lexicon, LexiconResponse
from emmio.sentence import SentenceDatabase
from emmio.teacher import Teacher
from emmio.ui import Logger, set_log, Interface, progress
from emmio.user_data import UserData

"""
<y> or <Enter>  I know at least one meaning of the word
<n>             I don’t know any of meanings of the word
<s>             I know at least one meanings of the word and I’m sure I
                will not forget it, skip this word in the future
<b>             I don’t know any of meanings of the word, but it is a proper
                name too
<->             the word doesn’t exist or is a proper name

<q>             exit
"""

HELP: str = """
help                print this message
exit / quit         close Emmio

Learning

learn / {Enter}     start learning process
stat learn          print learning statistics
plot learn          show depth graph
response time       show response time graph
next question time  show next question time graph
actions [per day]   show actions graph

Lexicon

lexicon             check lexicons
stat lexicon        print lexicon statistics
plot lexicon        draw lexicon graph
"""


class Emmio:
    """
    Emmio entry point.
    """

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
            print(HELP)

        if not command or command == "learn":
            self.learn()

        if command.startswith("lexicon"):
            self.run_lexicon(command[len("lexicon") :])

        if command == "stat learn":
            stat: dict[int, int] = defaultdict(int)
            total: int = 0
            for course_id in self.user_data.course_ids:
                k = self.user_data.get_course(course_id).knowledges
                for word in k:
                    if k[word].interval.total_seconds() == 0:
                        continue
                    depth = k[word].get_depth()
                    stat[depth] += 1
                    total += 1 / (2**depth)

            rows = []

            total_to_repeat: int = 0
            total_new: int = 0
            total_all: int = 0

            for course_id in self.user_data.course_ids:
                learning: Learning = self.user_data.get_course(course_id)
                row = [
                    learning.name,
                    progress((to_repeat := learning.to_repeat())),
                    progress((new := learning.ratio - learning.new_today())),
                    str((all_ := learning.learning())),
                ]
                rows.append(row)
                total_to_repeat += to_repeat
                total_new += new
                total_all += all_

            if total_to_repeat or total_new:
                footer = [
                    "Total",
                    str(total_to_repeat),
                    str(total_new),
                    str(total_all),
                ]
                rows.append(footer)

            self.interface.print(f"Pressure: {total:.2f}")

            self.interface.table(["Course", "Repeat", "New", "All"], rows)

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
            self.fill_data("en", "en_opensubtitles_2016")

        if command in Visualizer.get_commands():
            ratios = 0
            learning_words = 0
            records: list[Record] = []
            knowledges = {}
            for course_id in self.user_data.course_ids:
                learning = self.user_data.get_course(course_id)
                ratios += learning.ratio
                learning_words += learning.learning()
                records += learning.records
                knowledges |= learning.knowledges

            visualizer = Visualizer(interactive=interactive)
            records = sorted(records, key=lambda x: x.time)

            visualizer.process_command(command, records, knowledges)

    def run_lexicon(self, code: str) -> None:
        """Check all user lexicons."""

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
                self.get_dictionaries(language),
                "frequency",
                False,
                False,
                need,
            )
            break

    def learn(self) -> None:
        for course_id in self.user_data.course_ids:
            learning: Learning = self.user_data.get_course(course_id)
            lexicon: Lexicon = self.user_data.get_lexicon(
                construct_language(learning.subject)
            )
            for frequency_list_id in learning.frequency_list_ids:
                frequency_list: Optional[
                    FrequencyList
                ] = self.user_data.get_frequency_list(frequency_list_id)

                if frequency_list.update and self.frequency_db.has_table(
                    frequency_list_id
                ):
                    self.frequency_db.drop_table(frequency_list_id)

                if not self.frequency_db.has_table(frequency_list_id):
                    self.frequency_db.add_table(
                        frequency_list_id, frequency_list
                    )

            if learning.to_repeat() > 0:
                self.interface.header(f"Repeat learned for {learning.name}")
                teacher: Teacher = Teacher(
                    Path("cache"),
                    self.interface,
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
                self.user_data.get_course(x).learning()
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

    def fill_data(self, language, fl) -> None:
        fr = self.user_data.get_frequency_list(fl)

        words = {}
        learn: Learning = self.user_data.get_course(f"ru_{language}")
        for record in learn.records:
            if record.question_id not in words:
                words[record.question_id] = {
                    "word": record.question_id,
                    "language": language,
                    "addTime": record.time,
                    "nextQuestionTime": record.time + record.interval,
                    "vector": record.answer.value,
                    "index": fr.get_index(record.question_id),
                }
            elif record.question_id in words:
                words[record.question_id]["nextQuestionTime"] = (
                    record.time + record.interval
                )
                words[record.question_id]["vector"] += record.answer.value

        lexicon: Lexicon = self.user_data.get_lexicon(
            construct_language(language)
        )
        for word in lexicon.words:
            if word not in words:
                words[word] = {
                    "word": word,
                    "language": language,
                    "addTime": datetime.now(),
                    "nextQuestionTime": datetime.now(),
                    "vector": "N"
                    if lexicon.words[word].knowing
                    == LexiconResponse.DO_NOT_KNOW
                    else "Y",
                    "index": fr.get_index(word),
                }

        min_add_time = min(words[x]["addTime"] for x in words)
        max_add_time = max(words[x]["addTime"] for x in words)
        min_next_question_time = min(
            words[x]["nextQuestionTime"] for x in words
        )
        max_next_question_time = max(
            words[x]["nextQuestionTime"] for x in words
        )

        min_time = min(min_add_time, min_next_question_time)
        max_time = max(max_add_time, max_next_question_time)

        for word in words:
            words[word]["addTime"] = (
                words[word]["addTime"] - min_add_time
            ).total_seconds()
            words[word]["nextQuestionTime"] = (
                words[word]["nextQuestionTime"] - min_time
            ).total_seconds()

        w = []

        for word in words:
            w.append(words[word])

        w = list(sorted(w, key=lambda x: x["index"]))

        with (Path("web") / f"{language}.js").open("w") as output_file:
            output_file.write(f"{language} = ")
            json.dump(w, output_file)
            output_file.write(";")


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
    main()
