import math
import random
from datetime import timedelta, datetime
from enum import Enum
from pathlib import Path
from time import sleep
from typing import Optional

import telebot
import telebot.apihelper
from telebot import types
from telebot.types import Message

from emmio import ui, util
from emmio.dictionary import Dictionaries, DictionaryItem, Dictionary
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.language import GERMAN, Language, construct_language
from emmio.learning.core import Learning, ResponseType, SMALLEST_INTERVAL
from emmio.sentence.core import Translation
from emmio.sentence.sentences import Sentences
from emmio.sentence.database import SentenceDatabase
from emmio.ui import debug
from emmio.user_data import UserData


class Worker:
    def __lt__(self, other: "Worker") -> bool:
        raise NotImplementedError()

    def is_ready(self) -> bool:
        pass

    @staticmethod
    def get_greetings() -> str:
        return "Hello."

    def has_next_question(self):
        pass

    def get_next_question(self) -> list[str]:
        pass

    def process_answer(self, message):
        pass


class LearningWorker(Worker):
    def __init__(
        self,
        learning: Learning,
        user_data: UserData,
        cache_directory: Path,
        sentence_db,
    ):
        self.user_data: UserData = user_data
        self.learning: Learning = learning

        self.known_language: Language = learning.language
        self.learning_language: Optional[Language]
        try:
            self.learning_language = construct_language(learning.subject)
        except KeyError:
            self.learning_language = None

        self.interface: ui.Interface = ui.TelegramInterface()

        self.dictionaries: list[Dictionary] = [
            EnglishWiktionary(cache_directory, self.learning_language)
        ]
        self.sentences: Sentences = Sentences(
            cache_directory,
            sentence_db,
            self.known_language,
            self.learning_language,
        )

        self.skip: set[str] = set()

        # Current word status.
        self.word: Optional[str] = None
        self.interval = None
        self.index: int = 0
        self.alternative_forms: set[str] = set()
        self.current_sentences: list[Translation] = []
        self.items: list[DictionaryItem] = []

    def print_state(self):
        debug(
            f"sent.: {self.index}/{len(self.current_sentences)}, "
            f"skip: {len(self.skip)}, "
            f"to repeat: {self.learning.to_repeat(self.skip)}"
        )

    def __lt__(self, other: "LearningWorker") -> bool:
        return self.learning.get_nearest(
            self.skip
        ) < other.learning.get_nearest(self.skip)

    def is_ready(self) -> bool:
        return self.learning.is_ready(self.skip)

    def get_sentence(
        self, show_index: bool = False, max_translations: int = 3
    ) -> str:
        """
        Print sentence and its translations.

        :param show_index: show current sentence index
        :param max_translations: maximum number of translations to show
        """
        if self.index >= len(self.current_sentences):
            return ""

        text: str = self.current_sentences[self.index].sentence.text
        if show_index:
            text += f" ({self.index + 1}/{len(self.current_sentences)})"

        r: str = ""

        w = ""
        for position, char in enumerate(text):
            position: int
            char: str
            if self.learning_language.has_symbol(char.lower()):
                w += char
            else:
                if w:
                    if w.lower() == self.word:
                        r += "░" * len(self.word)
                    else:
                        r += w
                r += char
                w = ""

        for i in range(max_translations):
            if len(self.current_sentences[self.index].translations) > i:
                r += (
                    "\n"
                    + self.current_sentences[self.index].translations[i].text
                )

        return r

    def get_next_question(self) -> list[str]:

        debug("get_next_question()")
        self.print_state()

        if self.index > 0:
            if self.index < len(self.current_sentences):
                return [self.get_sentence(max_translations=1)]
            elif self.index == len(self.current_sentences):
                return ["No more sentences."]

        self.word = self.learning.get_next(self.skip)
        if not self.word:
            return ["No more words."]

        self.interval = self.learning.knowledges[self.word].interval

        ids_to_skip: set[int] = set()
        if self.word in self.user_data.exclude_sentences:
            ids_to_skip = set(self.user_data.exclude_sentences[self.word])

        self.current_sentences: list[Translation] = self.sentences.filter_(
            self.word, ids_to_skip, 120
        )
        if self.interval.total_seconds() == 0:
            self.current_sentences = sorted(
                self.current_sentences, key=lambda x: len(x.sentence.text)
            )
        else:
            random.shuffle(self.current_sentences)

        dictionaries: Dictionaries = Dictionaries(self.dictionaries)

        def log_(interval):
            if interval.total_seconds() == 0:
                return 0
            return int(math.log(interval.total_seconds() / 60 / 60 / 24, 2)) + 1

        index: int = 0

        self.alternative_forms: set[str] = set()
        exclude_translations: set[str] = set()

        if self.word in self.user_data.exclude_translations:
            exclude_translations = set(
                self.user_data.exclude_translations[self.word]
            )

        self.items: list[DictionaryItem] = dictionaries.get_items(self.word)

        if self.learning_language == GERMAN:
            for item in dictionaries.get_items(
                self.word[0].upper() + self.word[1:]
            ):
                if item not in self.items:
                    self.items.append(item)

        words_to_hide: set[str] = set()
        for item in self.items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link.link_value)

        result: list[str] = []
        statistics: str = ""
        if self.interval.total_seconds() > 0:
            statistics += "◕ " * log_(self.interval) + "\n"

        if self.items:
            translation_list = [
                x.to_str(
                    self.known_language,
                    self.interface,
                    False,
                    words_to_hide=words_to_hide | exclude_translations,
                    hide_translations=exclude_translations,
                )
                for x in self.items
            ]
            result.append(statistics + "\n".join(translation_list))
            self.alternative_forms = set(
                x.link_value for x in self.items[0].get_links()
            )
        else:
            result.append("No translations.")

        if index < len(self.current_sentences):
            result.append(self.get_sentence(max_translations=1))

        self.print_state()

        return result

    def process_answer(self, message):

        debug("process_answer()")
        self.print_state()

        answer: str = message

        sentence_id: int = (
            self.current_sentences[self.index].sentence.id_
            if self.index < len(self.current_sentences)
            else 0
        )

        # Preprocess answer.
        answer: str = self.learning_language.decode_text(answer)

        self.index += 1

        if answer == self.word:

            self.index = 0

            self.learning.register(
                ResponseType.RIGHT, sentence_id, self.word, self.interval * 2
            )
            if self.items:
                string_items: list[str] = [
                    x.to_str(self.known_language, self.interface)
                    for x in self.items
                ]
                self.interface.print("\n".join(string_items))

            self.learning.write()

            self.print_state()
            return (
                "Right"
                + (
                    f", {self.learning.to_repeat()} to repeat"
                    if self.learning.to_repeat()
                    else ""
                )
                + "."
            )

        elif answer in self.alternative_forms:
            self.print_state()
            return "Right form."

        elif answer in ["/skip", "Skip"]:
            self.skip.add(self.word)
            self.index = 0
            self.print_state()
            return "Skipped for this session."

        elif answer == "/stop":
            return "Stop."

        elif answer in ["/no", "Don't know"]:

            self.interface.box(self.word)
            if self.items:
                string_items: list[str] = [
                    x.to_str(self.known_language, self.interface)
                    for x in self.items
                ]
                self.interface.print("\n".join(string_items))
            self.interface.box(self.word)

            new_answer = self.interface.input("Learn word? ")
            if not new_answer:
                self.learning.register(
                    ResponseType.WRONG,
                    sentence_id,
                    self.word,
                    SMALLEST_INTERVAL,
                )
            else:
                self.learning.register(
                    ResponseType.SKIP, sentence_id, self.word, timedelta()
                )

            self.learning.write()
            self.index = 0

            self.print_state()
            return f"Right answer: {self.word}."

        elif answer == "/exclude":
            self.user_data.exclude_sentence(self.word, sentence_id)
            self.skip.add(self.word)
            self.print_state()
            return "Sentence was excluded."

        elif answer.startswith("/hide "):
            parts = answer.split(" ")
            self.user_data.exclude_translation(self.word, " ".join(parts[1:]))
            self.skip.add(self.word)
            self.print_state()
            return "Translation was hidden."

        else:
            self.print_state()
            return "No."

    def get_greetings(self) -> str:
        return self.learning.name


class LexiconWorker(Worker):
    def __lt__(self, other: "LexiconWorker") -> bool:
        pass

    def is_ready(self) -> bool:
        pass

    def do(self) -> None:
        pass


class ServerState(Enum):
    NOTHING = "nothing"
    WORKER = "worker"
    ASKING = "asking"
    PROCESSING = "processing"


class Server:
    def send(self, message: str):
        pass

    def receive(self, message: str):
        pass


class TelegramServer(Server):
    def __init__(self, user_data: UserData, bot) -> None:
        self.user_data: UserData = user_data
        sentence_db: SentenceDatabase = SentenceDatabase(
            user_data.path / "sentence.db"
        )
        self.learnings: list[LearningWorker] = [
            LearningWorker(
                user_data.get_course(x), user_data, Path("cache"), sentence_db
            )
            for x in user_data.course_ids
        ]
        self.lexicons: list[LexiconWorker] = []
        self.bot: telebot.TeleBot = bot
        self.id_: int = 0

        self.worker: Optional[Worker] = None
        self.state: ServerState = ServerState.NOTHING

    def start(self, message):
        self.id_ = message.chat.id
        self.step(message.text)
        self.bot.register_next_step_handler(message, self.receive_message)

    def send(self, message: str, markup=None):
        self.bot.send_message(self.id_, message, reply_markup=markup)

    def receive_message(self, message: Message):
        self.id_ = message.chat.id
        self.step(message.text)
        self.bot.register_next_step_handler(message, self.receive_message)

    def status(self) -> None:
        if not self.id_:
            return
        if self.state == ServerState.ASKING:
            self.send("Waiting for answer.")
        elif self.state == ServerState.NOTHING:
            now = datetime.now()
            time_to_repetition: timedelta = (
                min(x.get_nearest() for x in self.user_data.courses.values())
                - now
            )
            time_to_new: timedelta = util.day_end(now) - now

            if time_to_repetition < time_to_new:
                self.send(f"Repetition in {time_to_repetition}.")
            else:
                self.send(f"New question in {time_to_new}.")
        else:
            self.send("Alive.")

    def statistics(self, message: Message):
        self.send(message.text)

    def step(self, message: Optional[str] = None):

        if self.state == ServerState.NOTHING:

            while True:
                if self.learnings and (
                    (nearest := sorted(self.learnings)[0]).is_ready()
                ):
                    self.worker = nearest
                    self.send(nearest.get_greetings())
                    self.state = ServerState.WORKER
                    self.step()
                    break
                elif self.lexicons and (
                    (nearest := sorted(self.lexicons)[0]).is_ready()
                ):
                    self.worker = nearest
                    self.send(nearest.get_greetings())
                    self.state = ServerState.WORKER
                    self.step()
                    break
                else:
                    debug(f"{datetime.now()} Waiting...")
                    sleep(60)

        elif self.state == ServerState.WORKER:
            if self.worker.is_ready():
                markup = types.ReplyKeyboardMarkup(
                    row_width=2, resize_keyboard=False
                )
                markup.add(
                    types.KeyboardButton("Skip"),
                    types.KeyboardButton("Don't know"),
                )
                for text in self.worker.get_next_question():
                    self.send(text)
                self.state = ServerState.ASKING
            else:
                self.send("No more questions.")
                self.state = ServerState.NOTHING
                self.step()

        elif self.state == ServerState.ASKING:
            respond: str = self.worker.process_answer(message)
            if respond:
                self.send(respond)
                if respond.startswith("Right answer"):
                    sleep(1.5)
                elif respond.startswith("Right"):
                    sleep(0.4)

            self.state = ServerState.WORKER
            self.step()
