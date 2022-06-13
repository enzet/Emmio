import math
import random
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import telebot
import telebot.apihelper
from telebot.types import Message

from emmio import ui
from emmio.dictionary import Dictionaries, DictionaryItem, Dictionary
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.language import GERMAN, Language, construct_language
from emmio.learning import Learning, ResponseType, SMALLEST_INTERVAL
from emmio.sentence import Translation, Sentences, SentenceDatabase
from emmio.user_data import UserData


class Worker:
    def __lt__(self, other: "Worker") -> bool:
        raise NotImplementedError()

    def is_ready(self) -> bool:
        pass

    @staticmethod
    def get_greatings() -> str:
        return "Hello."

    def has_next_question(self):
        pass

    def get_next_question(self):
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
        self.skip: set[str] = set()

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

        # Current word status.
        self.word: Optional[str] = None
        self.interval = None
        self.index: int = 0
        self.alternative_forms: set[str] = set()
        self.current_sentences: list[Translation] = []
        self.items: list[DictionaryItem] = []

    def __lt__(self, other: "LearningWorker") -> bool:
        return self.learning.get_nearest(
            self.skip
        ) < other.learning.get_nearest(self.skip)

    def is_ready(self) -> bool:
        return self.learning.is_ready(self.skip)

    def get_sentence(self, show_index: bool = False, max_translations: int = 3):
        """
        Print sentence and its translations.

        :param show_index: show current sentence index
        :param max_translations: maximum number of translations to show
        """
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

    def get_next_question(self) -> str:

        if self.index > 0:
            if self.index < len(self.current_sentences):
                return self.get_sentence(max_translations=1)
            elif self.index == len(self.current_sentences):
                return "No more sentences."

        self.word = self.learning.get_next(self.skip)
        if not self.word:
            return "No more words."

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
                words_to_hide.add(link.link)

        result: str = ""
        if self.interval.total_seconds() > 0:
            result += "◕ " * log_(self.interval)

        if self.items:
            translation_list = [
                x.to_str(
                    self.known_language.get_code(),
                    self.interface,
                    False,
                    words_to_hide=words_to_hide | exclude_translations,
                    hide_translations=exclude_translations,
                )
                for x in self.items
            ]
            result += "\n" + "\n".join(translation_list)
            self.alternative_forms = set(
                x.link for x in self.items[0].get_links()
            )
        else:
            result += "\nNo translations."

        if index < len(self.current_sentences):
            result += "\n\n" + self.get_sentence(max_translations=1)

        return result

    def process_answer(self, message):

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
                    x.to_str(self.known_language.get_code(), self.interface)
                    for x in self.items
                ]
                self.interface.print("\n".join(string_items))

            self.learning.write()

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
            return "Right form."

        elif answer == "/skip":
            self.skip.add(self.word)
            self.index = 0
            return "Skipped for this session."

        elif answer == "/stop":
            return "Stop."

        elif answer == "/no":

            self.interface.box(self.word)
            if self.items:
                string_items: list[str] = [
                    x.to_str(self.known_language.get_code(), self.interface)
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

            return f"Right answer: {self.word}."

        elif answer == "/exclude":
            self.user_data.exclude_sentence(self.word, sentence_id)
            self.skip.add(self.word)
            return "Sentence was excluded."

        elif answer.startswith("/hide "):
            parts = answer.split(" ")
            self.user_data.exclude_translation(self.word, " ".join(parts[1:]))
            self.skip.add(self.word)
            return "Translation was hidden."

        else:
            return "No."

    def get_greatings(self) -> str:
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
        print(user_data.path)
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

    def send(self, message: str):
        self.bot.send_message(self.id_, message)

    def receive_message(self, message: Message):
        self.id_ = message.chat.id
        self.step(message.text)
        self.bot.register_next_step_handler(message, self.receive_message)

    def step(self, message: Optional[str] = None):

        if self.state == ServerState.NOTHING:

            if self.learnings and (
                (nearest := sorted(self.learnings)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greatings())
                self.state = ServerState.WORKER
                self.step()
            elif self.learnings and (
                (nearest := sorted(self.learnings)[0]).is_ready()
            ):
                self.worker = nearest
                self.send(nearest.get_greatings())
                self.state = ServerState.WORKER
                self.step()
            else:
                self.send("Nothing to do.")

        elif self.state == ServerState.WORKER:
            if self.worker.is_ready():
                self.send(self.worker.get_next_question())
                self.state = ServerState.ASKING
            else:
                self.send("No more questions.")
                self.state = ServerState.NOTHING
                self.step()

        elif self.state == ServerState.ASKING:
            respond: str = self.worker.process_answer(message)
            if respond:
                self.send(respond)

            self.state = ServerState.WORKER
            self.step()
