import math
import random
from datetime import timedelta
from pathlib import Path
from typing import Optional

from emmio import ui
from emmio.dictionary import Dictionary, DictionaryItem, Dictionaries
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.language import (
    Language,
    construct_language,
    LanguageNotFound,
    GERMAN,
)
from emmio.learning.core import Learning, ResponseType, SMALLEST_INTERVAL
from emmio.sentence.core import Translation, Sentence
from emmio.sentence.sentences import Sentences
from emmio.server import Worker, HIDE_SYMBOL
from emmio.ui import debug
from emmio.user_data import UserData


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
        except LanguageNotFound:
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

        result: str = ""
        word: str = ""

        for position, character in enumerate(text):
            position: int
            character: str
            if self.learning_language.has_symbol(character.lower()):
                word += character
            else:
                if word:
                    if word.lower() == self.word:
                        result += HIDE_SYMBOL * len(self.word)
                    else:
                        result += word
                result += character
                word = ""

        translations: list[Sentence] = self.current_sentences[
            self.index
        ].translations

        for index in range(max_translations):
            if len(translations) > index:
                result += "\n" + translations[index].text

        return result

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
            result.append(statistics + "\nNo translations.")

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
