"""Teacher."""
import logging
import math
from datetime import timedelta

from emmio.audio.core import AudioCollection
from emmio.data import Data
from emmio.dictionary.core import DictionaryItem, DictionaryCollection
from emmio.language import GERMAN
from emmio.learn.core import Learning, Response
from emmio.lexicon.core import (
    LexiconLog,
    LexiconResponse,
    WordSelection,
    Lexicon,
)
from emmio.lists.core import List
from emmio.sentence.core import SentenceTranslations, SentencesCollection
from emmio.ui import Interface
from emmio.user.data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class Teacher:
    def __init__(
        self,
        interface: Interface,
        data: Data,
        user_data: UserData,
        learning: Learning,
    ) -> None:
        self.interface: Interface = interface
        self.data: Data = data

        self.learning: Learning = learning
        self.lexicon: Lexicon = user_data.get_lexicon(
            self.learning.learning_language
        )
        self.word_index: int = 0
        self.words: list[tuple[str, List, int]] = []
        for list_id in self.learning.config.lists:
            list_ = data.get_list(list_id)
            for index, word in enumerate(list_.get_words()):
                self.words.append((word, list_, index))

        self.stop_after_answer: bool = False

        self.dictionaries: DictionaryCollection = data.get_dictionaries(
            self.learning.config.dictionaries
        )
        self.sentences: SentencesCollection = data.get_sentences_collection(
            self.learning.config.sentences
        )
        self.audio: AudioCollection = data.get_audio_collection(
            self.learning.config.audio
        )
        self.max_for_day: int = self.learning.config.max_for_day

    @staticmethod
    def get_smallest_interval() -> timedelta:
        return timedelta(minutes=5)

    @staticmethod
    def increase_interval(interval: timedelta) -> timedelta:
        if interval == timedelta(minutes=5):
            return timedelta(hours=8)
        elif interval == timedelta(hours=8):
            return timedelta(days=1)
        return interval * 2

    def get_new_question(self) -> str | None:
        for question_id, list_, index in self.words[self.word_index :]:
            logging.info(f"{index}th word from {list_.get_name()}")

            self.word_index += 1

            # Check whether the learning process already has the word: whether
            # it was initially known or it is learning.
            if self.learning.has(question_id):
                if self.learning.is_initially_known(question_id):
                    logging.info("Was initially known")
                else:
                    logging.info("Already learning")
                continue

            # Check user lexicon. Skip the word if it was mark as known by user
            # while checking lexicon.
            if (
                self.learning.config.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
            ):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.info("Known in lexicon")
                    continue

            # Request word definition in the dictionary.
            items: list[DictionaryItem] = self.dictionaries.get_items(
                question_id, self.learning.learning_language
            )

            # Skip word if current dictionaries has no definitions for it.
            if not items:
                logging.info("No definition")
                continue

            # Skip word if it is known that it is solely a form of other words.
            items_no_links: list[DictionaryItem] = self.dictionaries.get_items(
                question_id, self.learning.learning_language, follow_links=False
            )

            not_common = False
            for item in items_no_links:
                for language in self.learning.base_languages:
                    if item.has_definitions() and item.is_not_common(language):
                        not_common = True
                        break
            if not_common:
                logging.info("Not common")
                continue

            # Check user lexicon. Skip the word if it was mark as known by user
            # while checking lexicon. This should be done after checking
            # definitions in dictionary, because if user answer is "no", the
            # learning process starts immediately.
            if (
                self.learning.config.check_lexicon
                and self.lexicon
                and self.lexicon.has(question_id)
            ):
                if self.lexicon.get(question_id) != LexiconResponse.DONT:
                    logging.info("Known in lexicon")
                    continue
                else:
                    logging.info("Lexicon response was DONT KNOW")
                    # FIXME: user response may be DONT KNOW, but the word is
                    #        still may be just a form or not common, so we don't
                    #        want to learn it.
                    return question_id

            # If `ask_lexicon` option is enabled, show the word to user before
            # testing.
            if self.learning.config.ask_lexicon and not self.lexicon.has(
                question_id
            ):
                if not self.lexicon.has_log("log_ex"):
                    self.lexicon.add_log(
                        LexiconLog("log_ex", WordSelection("top"))
                    )
                self.lexicon.write()

                _, response, _ = self.lexicon.ask(
                    self.interface,
                    question_id,
                    [],
                    self.dictionaries,
                    log_name="log_ex",
                )
                if response is None:
                    return None

                if response == LexiconResponse.DONT:
                    logging.info("Lexicon response was DONT KNOW")
                    return question_id
                else:
                    logging.info("Lexicon response was KNOW")
                    continue

            logging.info("Nothing is known about the word")
            return question_id

        return None

    def start(self) -> bool:
        """
        Start the learning process: repeat old questions and learn new ones.

        :return: true if the learning process was finished, false if the
            learning process was interrupted by the user.
        """
        while True:
            # Learn new questions.

            if (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := self.get_new_question()) is not None
            ):
                code: str = self.learn(question_id, timedelta())
                if code == "stop":
                    return False
                continue

            # Repeat old questions.

            if (question_id := self.learning.get_next_question()) is not None:
                code: str = self.learn(
                    question_id, self.learning.knowledge[question_id].interval
                )
                if code == "stop":
                    return False

        return True

    def repeat(self) -> bool:
        while True:
            if word := self.learning.get_next_question():
                code: str = self.learn(
                    word, self.learning.knowledge[word].interval
                )
                if code != "bad question":
                    self.learning.write()
                if code == "stop":
                    return False
            else:
                return True

    def learn_new(self) -> bool:
        while True:
            if (
                self.learning.count_questions_added_today() < self.max_for_day
                and (question_id := self.get_new_question()) is not None
            ):
                code: str = self.learn(question_id, timedelta())
                if code != "bad question":
                    self.learning.write()
                if code == "stop":
                    return False
            else:
                return True

    def play(self, word: str):
        self.audio.play(word, self.learning.learning_language)

    def learn(self, word: str, interval: timedelta) -> str:
        ids_to_skip: set[int] = set()
        # if word in self.data.exclude_sentences:
        #     ids_to_skip = set(self.data.exclude_sentences[word])

        sentences: list[SentenceTranslations] = self.sentences.filter_by_word(
            word, ids_to_skip, 120
        )
        # if interval.total_seconds() == 0:
        sentences = sorted(sentences, key=lambda x: len(x.sentence.text))
        # else:
        #     random.shuffle(sentences)

        def print_sentence(show_index: bool = False, max_translations: int = 3):
            """
            Print sentence and its translations.

            :param show_index: show current sentence index
            :param max_translations: maximum number of translations to show
            """
            text: str = sentences[index].sentence.text
            if show_index:
                text += f" ({index + 1}/{len(sentences)})"

            result: str = ""

            current_word: str = ""
            for position, char in enumerate(text):
                position: int
                char: str
                if self.learning.learning_language.has_symbol(char.lower()):
                    current_word += char
                else:
                    if current_word:
                        if current_word.lower() == word:
                            result += "░" * len(word)
                        else:
                            result += current_word
                    result += char
                    current_word = ""

            for i in range(max_translations):
                if len(sentences[index].translations) > i:
                    result += "\n" + sentences[index].translations[i].text

            self.interface.print(result)

        def log_():
            if interval.total_seconds() == 0:
                return 0
            return int(math.log(interval.total_seconds() / 60 / 60 / 24, 2)) + 1

        index: int = 0

        statistics: str
        if interval.total_seconds() > 0:
            statistics = f"{'★ ' * log_()} "
        else:
            statistics = "New question  "

        statistics += (
            f"skipped: {self.learning.get_skipping_counter(word)}  "
            f"added today: {self.learning.count_questions_added_today()}  "
            f"to repeat: {self.learning.count_questions_to_repeat()}"
        )

        alternative_forms: set[str] = set()
        exclude_translations: set[str] = set()

        # if word in self.data.exclude_translations:
        #     exclude_translations = set(self.data.exclude_translations[word])

        items: list[DictionaryItem] = self.dictionaries.get_items(
            word, self.learning.learning_language
        )

        words_to_hide: set[str] = set()
        for item in items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link.link_value)

        if items:
            translation_list = [
                x.to_str(
                    self.learning.base_languages,
                    self.interface,
                    False,
                    words_to_hide=words_to_hide | exclude_translations,
                    hide_translations=exclude_translations,
                    only_common=False,
                )
                for x in items
            ]
            self.interface.print(
                statistics + "\n" + "\n".join(translation_list)
            )
            alternative_forms: set[str] = set(
                x.link_value for x in items[0].get_links()
            )
        else:
            self.interface.print(statistics + "\n" + "No translations.")

        if index < len(sentences):
            print_sentence()

        while True:
            answer: str = self.interface.get_word(
                word, alternative_forms, self.learning.learning_language
            )
            sentence_id: int = (
                sentences[index].sentence.id_ if index < len(sentences) else 0
            )

            # Preprocess answer.
            answer: str = self.learning.learning_language.decode_text(answer)

            if answer == word:
                self.learning.register(
                    Response.RIGHT,
                    sentence_id,
                    word,
                    self.increase_interval(interval),
                )
                if items:
                    string_items: list[str] = [
                        x.to_str(self.learning.base_languages, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))

                self.play(word)

                if self.stop_after_answer:
                    new_answer = self.interface.input(">>> ")
                    while new_answer:
                        if new_answer == "s":
                            self.learning.register(
                                Response.SKIP,
                                sentence_id,
                                word,
                                timedelta(),
                            )
                            break
                        new_answer = self.interface.input(">>> ")

                self.learning.write()

                return "ok"

            if answer in ["s", "/skip"]:
                self.learning.skip(word)
                return "ok"

            if answer.startswith("/skip "):
                _, word_to_skip = answer.split(" ")
                self.learning.register(
                    Response.SKIP,
                    0,
                    word_to_skip,
                    timedelta(),
                )
                self.learning.write()
                return "ok"

            if answer == "/stop":
                return "stop"

            if answer.startswith("/"):
                if answer == "/exclude":
                    self.data.exclude_sentence(word, sentence_id)
                    self.learning.skip(word)
                    return "ok"
                elif answer.startswith("/hide "):
                    self.data.exclude_translation(
                        word, " ".join(answer.split(" ")[1:])
                    )
                    self.learning.skip(word)
                    return "ok"
                elif answer.startswith("/btt "):
                    _, w, t = answer.split(" ")
                    self.data.exclude_translation(w, t)
                    continue

            if answer in [
                "/no",
                "n",  # Short for no, non, nein.
                "н",  # Short for нет.
                "ո",  # Short for ոչ.
            ]:
                self.interface.box(word)
                if items:
                    string_items: list[str] = [
                        x.to_str(self.learning.base_languages, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                self.interface.box(word)
                self.play(word)

                new_answer = self.interface.input("Learn word? ")
                if new_answer in ["s", "skip"]:
                    self.learning.register(
                        Response.SKIP, sentence_id, word, timedelta()
                    )
                else:
                    self.learning.register(
                        Response.WRONG,
                        sentence_id,
                        word,
                        self.get_smallest_interval(),
                    )

                self.learning.write()

                return "ok"

            if answer == "":
                index += 1
                if index < len(sentences):
                    print_sentence()
                elif index == len(sentences):
                    self.interface.print("No more sentences.")
