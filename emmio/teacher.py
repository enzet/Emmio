"""Teacher."""
import logging
import math
from datetime import timedelta

from emmio.data import Data
from emmio.dictionary.core import DictionaryItem, DictionaryCollection
from emmio.language import GERMAN
from emmio.learn.core import Learning, ResponseType
from emmio.lexicon.core import (
    LexiconResponse,
    LexiconLog,
    WordSelection,
)
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

        self.word_index: int = 0

        self.skip = set()

        self.learning = learning
        self.lexicon = user_data.get_lexicon(self.learning.learning_language)

        self.words: list[str] = []
        for list_id in self.learning.config.lists:
            self.words += data.get_words(list_id)

        self.stop_after_answer: bool = False

        self.dictionaries: DictionaryCollection = data.get_dictionaries(
            self.learning.config.dictionaries
        )
        self.sentences: SentencesCollection = data.get_sentences_collection(
            self.learning.config.sentences
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

    def start(self) -> bool:

        while True:
            word: str | None = self.learning.get_next(self.skip)

            if word:
                code: str = self.learn(
                    word, self.learning.knowledge[word].interval, 0
                )
                if code == "stop":
                    return False

                continue

            if self.learning.new_today() >= self.max_for_day:
                return True

            has_new_word: bool = False

            for index, word in self.words[self.word_index :]:

                self.word_index += 1

                # Check whether the learning process already has the word:
                # whether it was initially known or it is learning.
                if self.learning.has(word):
                    if self.learning.is_initially_known(word):
                        logging.debug(f"[{index}] was initially known")
                    else:
                        logging.debug(f"[{index}] already learning")
                    continue

                # Check user lexicon. Skip the word if it was mark as known by
                # user while checking lexicon.
                if (
                    self.learning.config.check_lexicon
                    and self.lexicon
                    and self.lexicon.has(word)
                    and self.lexicon.get(word) != LexiconResponse.DONT
                ):
                    logging.debug(f"[{index}] known in lexicon")
                    continue

                # Skip the word if it was skipped during the current learning
                # session.
                if word in self.skip:
                    logging.debug(f"[{index}] skipped")
                    continue

                items: list[DictionaryItem] = self.dictionaries.get_items(word)
                if not items and self.learning.learning_language == GERMAN:
                    for item in self.dictionaries.get_items(
                        word[0].upper() + word[1:]
                    ):
                        if item not in items:
                            items.append(item)

                # Skip word if current dictionaries has no definitions for it
                # or the word is solely a form of other words.
                if not items:
                    logging.debug(f"[{index}] no definition")
                    continue

                if not items[0].has_common_definition(
                    self.learning.base_language
                ):
                    logging.debug(f"[{index}] not common")
                    continue

                if self.learning.config.check_lexicon and self.lexicon.has(
                    word
                ):
                    if self.lexicon.get(word) != LexiconResponse.DONT:
                        logging.debug(f"[{index}] word is known")
                        continue
                    # TODO: else start learning

                if not self.lexicon.has_log("log_ex"):
                    self.lexicon.add_log(
                        LexiconLog("log_ex", WordSelection("top"))
                    )

                has_new_word: bool = True

                if self.learning.config.ask_lexicon and not self.lexicon.has(
                    word
                ):
                    self.lexicon.write()

                    _, response, _ = self.lexicon.ask(
                        self.interface,
                        word,
                        [],
                        self.dictionaries,
                        log_name="log_ex",
                    )
                    if response is None:
                        return False

                    if response != LexiconResponse.DONT:
                        continue

                code: str = self.learn(word, timedelta(), index)
                if code == "stop":
                    return False
                break

            if not has_new_word:
                break

        return True

    def repeat(self) -> bool:
        while True:
            has_repeat: bool = False
            word = self.learning.get_next(self.skip)
            if word:
                code: str = self.learn(
                    word, self.learning.knowledge[word].interval, 0
                )
                if code == "bad question":
                    self.skip.add(word)
                else:
                    self.learning.write()
                has_repeat = True
                if code == "stop":
                    return False
            if not has_repeat:
                break

        return True

    def learn(self, word: str, interval: timedelta, word_index: int) -> str:

        ids_to_skip: set[int] = set()
        # if word in self.data.exclude_sentences:
        #     ids_to_skip = set(self.data.exclude_sentences[word])

        sentences: list[SentenceTranslations] = self.sentences.filter_(
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

        statistics: str = ""
        if interval.total_seconds() > 0:
            statistics += f"{'◕ ' * log_()} "
        else:
            statistics += f"frequency index: {word_index}  "
        statistics += (
            f"new today: {self.learning.new_today()}  "
            f"to repeat: {self.learning.to_repeat()}"
        )

        alternative_forms: set[str] = set()
        exclude_translations: set[str] = set()

        # if word in self.data.exclude_translations:
        #     exclude_translations = set(self.data.exclude_translations[word])

        items: list[DictionaryItem] = self.dictionaries.get_items(word)

        if self.learning.learning_language == GERMAN:
            for item in self.dictionaries.get_items(word[0].upper() + word[1:]):
                if item not in items:
                    items.append(item)

        words_to_hide: set[str] = set()
        for item in items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link.link_value)

        if items:
            translation_list = [
                x.to_str(
                    self.learning.base_language,
                    self.interface,
                    False,
                    words_to_hide=words_to_hide | exclude_translations,
                    hide_translations=exclude_translations,
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
                    ResponseType.RIGHT,
                    sentence_id,
                    word,
                    self.increase_interval(interval),
                )
                if items:
                    string_items: list[str] = [
                        x.to_str(self.learning.base_language, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))

                if self.stop_after_answer:
                    new_answer = self.interface.input(">>> ")
                    while new_answer:
                        if new_answer == "s":
                            self.learning.register(
                                ResponseType.SKIP,
                                sentence_id,
                                word,
                                timedelta(),
                            )
                            break
                        new_answer = self.interface.input(">>> ")

                self.learning.write()

                return "ok"

            if answer in ["s", "/skip"]:
                self.skip.add(word)
                return "ok"

            if answer.startswith("/skip "):
                _, word_to_skip = answer.split(" ")
                self.learning.register(
                    ResponseType.SKIP,
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
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/hide "):
                    self.data.exclude_translation(
                        word, " ".join(answer.split(" ")[1:])
                    )
                    self.skip.add(word)
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
                        x.to_str(self.learning.base_language, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                self.interface.box(word)

                new_answer = self.interface.input("Learn word? ")
                if not new_answer:
                    self.learning.register(
                        ResponseType.WRONG,
                        sentence_id,
                        word,
                        self.get_smallest_interval(),
                    )
                else:
                    self.learning.register(
                        ResponseType.SKIP, sentence_id, word, timedelta()
                    )

                self.learning.write()

                return "ok"

            if answer == "":
                index += 1
                if index < len(sentences):
                    print_sentence()
                elif index == len(sentences):
                    self.interface.print("No more sentences.")
