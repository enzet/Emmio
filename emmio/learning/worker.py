import math
import random
import sys
from pathlib import Path
from typing import Optional

from emmio import ui
from emmio.dictionary import DictionaryItem, Dictionaries
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.frequency import FrequencyDatabase
from emmio.language import (
    Language,
    construct_language,
    LanguageNotFound,
    GERMAN,
)
from emmio.learning.core import Learning, ResponseType, SMALLEST_INTERVAL
from emmio.lexicon.core import (
    Lexicon,
    WordSelection,
    LexiconResponse,
    LexiconLog,
    AnswerType,
)
from emmio.sentence.core import Translation, Sentence
from emmio.sentence.database import SentenceDatabase
from emmio.sentence.sentences import Sentences
from emmio.text import sanitize
from emmio.ui import debug, log
from emmio.user_data import UserData
from emmio.util import HIDE_SYMBOL
from emmio.worker import Worker


class LearningWorker(Worker):
    def __init__(
        self,
        learning: Learning,
        lexicon: Lexicon,
        user_data: UserData,
        cache_directory: Path,
        sentence_db: SentenceDatabase,
        frequency_db: FrequencyDatabase,
    ):
        self.user_data: UserData = user_data
        self.learning: Learning = learning
        self.lexicon: Lexicon = lexicon

        self.known_language: Language = learning.language
        self.learning_language: Optional[Language]
        try:
            self.learning_language = construct_language(learning.subject)
        except LanguageNotFound:
            self.learning_language = None

        self.interface: ui.Interface = ui.TelegramInterface()

        self.dictionaries: Dictionaries = Dictionaries(
            [EnglishWiktionary(cache_directory, self.learning_language)]
        )
        self.sentences: Sentences = Sentences(
            cache_directory,
            sentence_db,
            self.known_language,
            self.learning_language,
        )

        self.skip: set[str] = set()

        self.question_ids: list[tuple[int, str]] = []
        log("getting words")
        for frequency_list_id in learning.frequency_list_ids:
            frequency_list_id: str
            for index, word, _ in frequency_db.get_words(frequency_list_id):
                index: int
                word: str
                self.question_ids.append((index, word))

        # Current word status.
        self.word: Optional[str] = None
        self.question_index: int = 0
        self.interval = None

        # If index > 0, show next sentence.
        self.index: int = 0

        self.alternative_forms: set[str] = set()
        self.current_sentences: list[Translation] = []
        self.items: list[DictionaryItem] = []

        self.state = ""

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
        self, show_index: bool = False, max_translations: int = 1
    ) -> str:
        """
        Print sentence and its translations.

        :param show_index: show current sentence index
        :param max_translations: maximum number of translations to show
        """
        if self.index >= len(self.current_sentences):
            return ""

        text: str = self.current_sentences[self.index].sentence.text
        text = sanitize(text, [self.word], HIDE_SYMBOL)
        if show_index:
            text += f" ({self.index + 1}/{len(self.current_sentences)})"

        translations: list[Sentence] = self.current_sentences[
            self.index
        ].translations

        return f"{text}\n" + "\n".join(
            translations[i].text
            for i in range(min(max_translations, len(translations)))
        )

    def get_next_question(self) -> list[str]:

        debug("get_next_question()")
        self.print_state()

        if self.index > 0:
            if self.index < len(self.current_sentences):
                return [self.get_sentence()]
            elif self.index == len(self.current_sentences):
                return ["No more sentences."]

        if self.learning.new_today() < self.learning.ratio:
            return self.get_new_question()

        return self.get_question_to_repeat()

    def get_new_question(self) -> list[str]:
        """Get new question from the question list."""
        for index, question_id in self.question_ids[self.question_index :]:
            self.question_index += 1

            if self.learning.has(question_id):
                if self.learning.is_initially_known(question_id):
                    debug(f"[{index}] was initially known")
                else:
                    debug(f"[{index}] already learning")
                continue

            if (
                self.learning.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
                and self.lexicon.get(question_id) != LexiconResponse.DONT
            ):
                debug(f"[{index}] known in lexicon")
                continue

            if question_id in self.skip:
                debug(f"[{index}] skipped")
                continue

            items: list[DictionaryItem] = self.dictionaries.get_items(
                question_id
            )
            if not items and self.learning_language == GERMAN:
                for item in self.dictionaries.get_items(
                    question_id[0].upper() + question_id[1:]
                ):
                    if item not in items:
                        items.append(item)

            # Skip word if current dictionaries has no definitions for it
            # or the word is solely a form of other words.
            if not items:
                debug(f"[{index}] no definition")
                continue

            if not items[0].has_common_definition(self.learning.language):
                debug(f"[{index}] not common")
                continue

            if self.learning.check_lexicon and self.lexicon.has(question_id):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    debug(f"[{index}] word is known")
                    continue
                else:
                    self.word = question_id
                    self.state = "waiting_lexicon_answer"
                    return [question_id + " ?"]

            if not self.lexicon.has_log("log_ex"):
                self.lexicon.add_log(LexiconLog("log_ex", WordSelection("top")))

            if self.learning.ask_lexicon and not self.lexicon.has(question_id):

                self.lexicon.write()

                self.word = question_id
                self.state = "waiting_lexicon_answer"
                return [question_id + " ?"]

    def get_question_to_repeat(self) -> list[str]:
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

        self.items: list[DictionaryItem] = self.dictionaries.get_items(
            self.word
        )

        if self.learning_language == GERMAN:
            for item in self.dictionaries.get_items(
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
            result.append(self.get_sentence())

        self.print_state()

        return result

    def process_answer(self, message: str) -> str:

        debug("process_answer()")
        self.print_state()

        if self.state == "waiting_lexicon_answer":

            to_skip = False

            if message == "Show definition.":
                self.state = "waiting_lexicon_answer"
                return ""  # definition(self.word)
            elif message in ["/know", "Know."]:
                response = LexiconResponse.KNOW
            elif message in ["/skip", "Know, skip."]:
                response = LexiconResponse.KNOW
                to_skip = True
            elif message in ["/not_a_word", "Not a word."]:
                response = LexiconResponse.NOT_A_WORD
                to_skip = True
            elif message in ["/but", "But."]:
                response = LexiconResponse.DONT_BUT_PROPER_NOUN_TOO
                to_skip = True
            else:
                response = LexiconResponse.DONT

            self.lexicon.register(
                self.word,
                response,
                to_skip,
                log_name="log_ex",
                answer_type=AnswerType.USER_ANSWER,
            )
            return ""

        sentence_id: int = (
            self.current_sentences[self.index].sentence.id_
            if self.index < len(self.current_sentences)
            else 0
        )

        # Preprocess answer.
        answer: str = self.learning_language.decode_text(message)

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
            sys.exit(0)

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
