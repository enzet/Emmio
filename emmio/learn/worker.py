import logging
import math
import random
from datetime import timedelta

from emmio import ui
from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection, DictionaryItem
from emmio.language import GERMAN
from emmio.learn.core import Learning, Response
from emmio.lexicon.core import (
    AnswerType,
    Lexicon,
    LexiconLog,
    LexiconResponse,
    WordSelection,
)
from emmio.sentence.core import (
    Sentence,
    SentencesCollection,
    SentenceTranslations,
)
from emmio.text import sanitize
from emmio.util import HIDE_SYMBOL
from emmio.worker import Worker

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class LearningWorker(Worker):
    """Server worker for learning process."""

    def __init__(self, learning: Learning, lexicon: Lexicon, data: Data):
        self.data: Data = data
        self.learning: Learning = learning
        self.lexicon: Lexicon = lexicon

        self.interface: ui.Interface = ui.TelegramInterface()

        self.dictionaries: DictionaryCollection = data.get_dictionaries(
            self.learning.config.dictionaries
        )
        self.sentences: SentencesCollection = data.get_sentences_collection(
            self.learning.config.sentences
        )

        self.skip: set[str] = set()

        self.question_ids: list[str] = []

        logging.debug("getting words")
        for list_id in learning.config.lists:
            for word in self.data.get_words(list_id):
                self.question_ids.append(word)

        # Current word status.
        self.word: str | None = None
        self.question_index: int = 0
        self.interval = None

        # If index > 0, show next sentence.
        self.index: int = 0

        self.alternative_forms: set[str] = set()
        self.current_sentences: list[SentenceTranslations] = []
        self.items: list[DictionaryItem] = []

        self.state = ""

    def print_state(self):
        logging.debug(
            f"sent.: {self.index}/{len(self.current_sentences)}, "
            f"skip: {len(self.skip)}, "
            f"to repeat: {self.learning.count_questions_to_repeat(self.skip)}"
        )

    def __lt__(self, other: "LearningWorker") -> bool:
        return self.learning.count_questions_to_repeat(
            self.skip
        ) > other.learning.count_questions_to_repeat(self.skip)

    def is_ready(self) -> bool:
        if self.learning.is_ready(self.skip):
            return True
        # FIXME: check if there is new questions.
        return True

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
        logging.debug("LearningWorker: get_next_question()")
        self.print_state()

        if self.index > 0:
            if self.index < len(self.current_sentences):
                return [self.get_sentence()]
            elif self.index == len(self.current_sentences):
                return ["No more sentences."]

        if q := self.get_question():
            return q

    def get_new_question(self) -> str:
        """Get new question from the question list."""
        for question_id in self.question_ids[self.question_index :]:
            self.question_index += 1

            if self.learning.has(question_id):
                if self.learning.is_initially_known(question_id):
                    logging.debug("Word skipped: was initially known.")
                else:
                    logging.debug("Word skipped: already learning.")
                continue

            if (
                self.learning.config.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
                and self.lexicon.get(question_id) != LexiconResponse.DONT
            ):
                logging.debug("Word skipped: known in lexicon.")
                continue

            if question_id in self.skip:
                logging.debug("Word skipped: skipped.")
                continue

            items: list[DictionaryItem] = self.dictionaries.get_items(
                question_id
            )
            if not items and self.learning.learning_language == GERMAN:
                for item in self.dictionaries.get_items(
                    question_id[0].upper() + question_id[1:]
                ):
                    if item not in items:
                        items.append(item)

            # Skip word if current dictionaries has no definitions for it
            # or the word is solely a form of other words.
            if not items:
                logging.debug("Word skipped: no definition.")
                continue

            if not items[0].has_common_definition(self.learning.base_language):
                logging.debug("Word skipped: it is not common.")
                continue

            if self.learning.config.check_lexicon and self.lexicon.has(
                question_id
            ):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.debug("Word skipped: it is already known.")
                    continue
                else:
                    self.word = question_id
                    self.state = "waiting_lexicon_answer"
                    return question_id

            if not self.lexicon.has_log("log_ex"):
                self.lexicon.add_log(LexiconLog("log_ex", WordSelection("top")))

            if self.learning.config.ask_lexicon and not self.lexicon.has(
                question_id
            ):
                self.lexicon.write()

                self.word = question_id
                self.state = "waiting_lexicon_answer"
                return question_id

            return question_id

    def get_question(self) -> list[str]:
        self.word = self.learning.get_next_question(self.skip)

        if not self.word:
            self.word = self.get_new_question()

        if not self.word:
            return []

        if self.word in self.learning.knowledge:
            self.interval = self.learning.knowledge[self.word].interval
        else:
            self.interval = timedelta()

        ids_to_skip: set[int] = set()
        # if self.word in self.data.exclude_sentences:
        #     ids_to_skip = set(self.data.exclude_sentences[self.word])

        self.current_sentences: list[SentenceTranslations] = (
            self.sentences.filter_by_word(self.word, ids_to_skip, 120)
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

        # if self.word in self.data.exclude_translations:
        #     exclude_translations = set(
        #         self.data.exclude_translations[self.word]
        #     )

        self.items: list[DictionaryItem] = self.dictionaries.get_items(
            self.word
        )

        if self.learning.learning_language == GERMAN:
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
                    self.learning.base_language,
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
        """Process answer provided by the user."""

        logging.debug("process_answer()")
        self.print_state()

        if self.state == "waiting_lexicon_answer":
            to_skip: bool = False

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
        answer: str = self.learning.learning_language.decode_text(message)

        self.index += 1

        state: str = (
            f", {self.learning.count_questions_to_repeat()} to repeat"
            if self.learning.count_questions_to_repeat()
            else ""
        )

        if answer == self.word:
            self.index = 0
            self.learning.register(Response.RIGHT, sentence_id, self.word)
            transcriptions: list[str] = []
            if self.items:
                for item in self.items:
                    for transcription in item.get_transcriptions():
                        if transcription not in transcriptions:
                            transcriptions.append(transcription)

            self.learning.write()

            self.print_state()
            return f"Right{state}, " + ", ".join(transcriptions) + "."

        elif answer in self.alternative_forms:
            self.print_state()
            return "Right form."

        elif answer in ["/skip", "Skip"]:
            self.skip.add(self.word)
            self.index = 0
            self.print_state()
            return f"Skipped for this session{state}."

        elif answer in ["/no", "Don't know"]:
            self.learning.register(Response.WRONG, sentence_id, self.word)
            self.learning.write()
            self.index = 0

            self.print_state()
            return f"Right answer: {self.word}{state}."

        else:
            self.print_state()
            return "No."

    def get_greetings(self) -> str:
        return self.learning.config.name
