import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from emmio import util
from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection
from emmio.graph import Visualizer
from emmio.language import construct_language
from emmio.learn.core import Learning, LearningRecord, Response
from emmio.lexicon.core import Lexicon
from emmio.lexicon.visualizer import LexiconVisualizer
from emmio.teacher import Teacher
from emmio.ui import Interface, progress
from emmio.user.data import UserData

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

    def __init__(
        self, path: Path, interface: Interface, data: Data, user_id: str
    ) -> None:

        self.path: Path = path
        self.interface: Interface = interface
        self.data: Data = data
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
            command: str = input("> ")

            if command in ["q", "quit", "exit"]:
                return

            self.process_command(command)

    def process_command(self, command: str, interactive: bool = True) -> None:

        data: Data = self.data

        if command == "help":
            self.interface.table(["Command", "Description"], HELP)

        if not command or command == "learn" or command.startswith("learn "):
            if command.startswith("learn "):
                _, id_ = command.split(" ")
                learnings = iter([self.data.get_learning(self.user_id, id_)])
            else:
                learnings: Iterator[Learning] = self.data.get_active_learnings(
                    self.user_id
                )
            self.learn(learnings)

        if command.startswith("lexicon"):
            self.run_lexicon(data, command[len("lexicon") :])

        if command == "stat learn":
            self.data.get_stat(self.interface, self.user_id)

        if command == "stat lexicon":

            rows = []

            for language in sorted(
                data.get_lexicon_languages(),
                key=lambda x: -self.user_data.get_lexicon(
                    x
                ).get_last_rate_number(),
            ):
                lexicon: Lexicon = self.user_data.get_lexicon(language)
                now: datetime = datetime.now()
                rate: float | None = lexicon.get_last_rate()
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
                    for language in data.get_lexicon_languages()
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
                    for language in data.get_lexicon_languages()
                ],
                1.5,
            )

        if command == "svg lexicon week":
            LexiconVisualizer().graph_with_svg(
                [
                    self.user_data.get_lexicon(language)
                    for language in data.get_lexicon_languages()
                ],
            )

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
                    ).get_items(word)

                    if not items:
                        rows.append([word])
                        continue

                    transcription, text = items[0].get_short(
                        learning.base_language
                    )
                    if transcription:
                        text = (
                            self.interface.colorize(transcription, "yellow")
                            + " "
                            + text
                        )
                    rows.append([word, text])

            self.interface.table(["Word", "Translation"], rows)

        if command == "schedule":
            hours = [0] * 24
            now = datetime.now()
            start = datetime(
                year=now.year, month=now.month, day=now.day, hour=now.hour
            )

            for learning in self.user_data.get_active_learnings():
                for question_id, knowledge in learning.knowledge.items():
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
            knowledge = {}
            for learning in self.user_data.get_active_learnings():
                ratios += learning.config.max_for_day
                learning_words += learning.count_questions_to_learn()
                records += learning.process.records
                knowledge |= learning.knowledge

            visualizer = Visualizer(interactive=interactive)
            records = sorted(records, key=lambda x: x.time)

            lexicons = [
                self.user_data.get_lexicon(learning.learning_language)
                for learning in self.user_data.get_active_learnings()
            ]
            visualizer.process_command(command, records, knowledge, lexicons)

        if command.startswith("listen "):
            _, code = command.split(" ")
            self.listen(self.data.get_learning(self.user_id, code))

    def listen(self, learning: Learning):
        audio_collection: AudioCollection = self.data.get_audio_collection(
            learning.config.audio
        )
        dictionary_collection: DictionaryCollection = (
            self.data.get_dictionaries(learning.config.dictionaries)
        )
        print(learning.config.name)
        question_ids: list[str] = learning.get_safe_question_ids()
        for question_id in question_ids:
            translation: str | None = None
            if items := dictionary_collection.get_items(question_id):
                translation: str | None = items[0].get_one_word_definition(
                    learning.base_language
                )
            if translation and " " not in translation:
                print("   ", question_id, "—", translation)
                if audio_collection.has(
                    translation, learning.base_language
                ) and audio_collection.has(
                    question_id, learning.learning_language
                ):
                    for _ in range(2):
                        audio_collection.play(
                            translation, learning.base_language
                        )
                        audio_collection.play(
                            question_id, learning.learning_language, 2
                        )
                        sleep(1)

    def run_lexicon(self, data: Data, code: str) -> None:
        """Check all user lexicons."""

        if code.endswith(" ra"):
            language_code = code[1:3]
            language = construct_language(language_code)
            lexicon = data.get_lexicon(language)
            lexicon.check(
                self.interface,
                data.get_frequency_list_for_lexicon(language),
                None,
                DictionaryCollection(self.get_dictionaries(language)),
                "most frequent",
                False,
                False,
                None,
                learning=data.get_course(f"ru_{language_code}"),
            )
            return

        priority_path: Path = self.path / "priority"
        priority_path.mkdir(parents=True, exist_ok=True)

        if code:
            languages = [construct_language(code[1:])]
        else:
            languages = sorted(
                data.get_lexicon_languages(),
                key=lambda x: -data.get_lexicon(x).get_last_rate_number(),
            )

        for language in languages:
            lexicon: Lexicon = data.get_lexicon(language)
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
                data.get_frequency_list_for_lexicon(language),
                None,
                DictionaryCollection(self.get_dictionaries(language)),
                "frequency",
                False,
                False,
                need,
            )
            break

    def learn(self, learnings) -> None:

        for learning in learnings:

            if learning.count_questions_to_repeat() > 0:
                self.interface.header(
                    f"Repeat learned for {learning.config.name}"
                )
                teacher: Teacher = Teacher(
                    self.interface, self.data, self.user_data, learning
                )
                if not teacher.repeat():
                    return

        for learning in learnings:
            if (
                learning.config.max_for_day
                > learning.count_questions_added_today()
            ):
                self.interface.header(
                    f"Learn new and repeat for {learning.config.name}"
                )
                teacher: Teacher = Teacher(
                    self.interface, self.data, self.user_data, learning
                )
                proceed = teacher.start()
                if not proceed:
                    return

        print()

        now: datetime = datetime.now()
        time_to_repetition: timedelta = (
            min(
                x.get_nearest()
                for x in self.user_data.learnings.learnings.values()
            )
            - now
        )
        time_to_new: timedelta = util.day_end(now) - now
        if time_to_repetition < time_to_new:
            print(f"    Repetition in {time_to_repetition}.")
        else:
            print(f"    New question in {time_to_new}.")
        print()
