"""Teacher."""
import math
import random
from datetime import timedelta
from pathlib import Path
from typing import Optional

from emmio.dictionary import Dictionaries, DictionaryItem
from emmio.frequency import FrequencyDatabase
from emmio.language import Language, construct_language, GERMAN
from emmio.learning.core import Learning, ResponseType
from emmio.lexicon.core import (
    Lexicon,
    LexiconResponse,
    LexiconLog,
    WordSelection,
)
from emmio.sentence.core import Translation
from emmio.sentence.sentences import Sentences
from emmio.sentence.database import SentenceDatabase
from emmio.ui import log, Interface, debug

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.user_data import UserData

SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class Teacher:
    def __init__(
        self,
        cache_directory_name: Path,
        interface: Interface,
        user_data: UserData,
        sentence_db: SentenceDatabase,
        frequency_db: FrequencyDatabase,
        learning: Learning,
        lexicon: Lexicon,
        get_dictionaries=None,
    ) -> None:
        self.interface: Interface = interface
        self.user_data: UserData = user_data
        self.known_language: Language = learning.language

        self.learning_language: Optional[Language]
        try:
            self.learning_language = construct_language(learning.subject)
        except KeyError:
            self.learning_language = None

        self.max_for_day: int = learning.ratio
        self.learning: Learning = learning
        self.dictionaries: Dictionaries = Dictionaries(
            get_dictionaries(self.learning_language)
        )

        self.lexicon: Lexicon = lexicon

        self.sentences: Sentences = Sentences(
            cache_directory_name,
            sentence_db,
            self.known_language,
            self.learning_language,
        )

        self.words: list[tuple[int, str]] = []
        log("getting words")
        for frequency_list_id in learning.frequency_list_ids:
            frequency_list_id: str
            for index, word, _ in frequency_db.get_words(frequency_list_id):
                index: int
                word: str
                if (
                    not self.learning.check_lexicon
                    or not self.lexicon
                    or not self.lexicon.has(word)
                    or self.lexicon.get(word) == LexiconResponse.DONT
                ):
                    self.words.append((index, word))

        self.skip = set()

        self.stop_after_answer: bool = False

    def start(self) -> bool:

        while True:
            word: Optional[str] = self.learning.get_next(self.skip)

            if word:
                code: str = self.learn(
                    word, self.learning.knowledges[word].interval, 0
                )
                if code == "stop":
                    return False

                continue

            if self.learning.new_today() >= self.max_for_day:
                return True

            has_new_word: bool = False

            for index, word in self.words:
                if self.learning.has(word):
                    if self.learning.is_initially_known(word):
                        debug(f"[{index}] was initially known")
                    else:
                        debug(f"[{index}] already learning")
                    continue

                if word in self.skip:
                    debug(f"[{index}] skipped")
                    continue

                items: list[DictionaryItem] = self.dictionaries.get_items(word)
                if not items and self.learning_language == GERMAN:
                    for item in self.dictionaries.get_items(
                        word[0].upper() + word[1:]
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

                if self.learning.check_lexicon and self.lexicon.has(word):
                    if self.lexicon.get(word) != LexiconResponse.DONT:
                        debug(f"[{index}] word is known")
                        continue
                    # TODO: else start learning

                if not self.lexicon.has_log("log_ex"):
                    self.lexicon.add_log(
                        LexiconLog("log_ex", WordSelection("top"))
                    )

                has_new_word = True

                if self.learning.ask_lexicon and not self.lexicon.has(word):

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
                    word, self.learning.knowledges[word].interval, 0
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
        if word in self.user_data.exclude_sentences:
            ids_to_skip = set(self.user_data.exclude_sentences[word])

        sentences: list[Translation] = self.sentences.filter_(
            word, ids_to_skip, 120
        )
        if interval.total_seconds() == 0:
            sentences = sorted(sentences, key=lambda x: len(x.sentence.text))
        else:
            random.shuffle(sentences)

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

            w = ""
            for position, char in enumerate(text):
                position: int
                char: str
                if self.learning_language.has_symbol(char.lower()):
                    w += char
                else:
                    if w:
                        if w.lower() == word:
                            result += "░" * len(word)
                        else:
                            result += w
                    result += char
                    w = ""

            for i in range(max_translations):
                if len(sentences[index].translations) > i:
                    result += "\n" + sentences[index].translations[i].text

            self.interface.print(result)

        def log_(interval):
            if interval.total_seconds() == 0:
                return 0
            return int(math.log(interval.total_seconds() / 60 / 60 / 24, 2)) + 1

        index: int = 0

        statistics: str = ""
        if interval.total_seconds() > 0:
            statistics += f"{'◕ ' * log_(interval)} "
        else:
            statistics += f"frequency index: {word_index}  "
        statistics += (
            f"new today: {self.learning.new_today()}  "
            f"to repeat: {self.learning.to_repeat()}"
        )

        alternative_forms: set[str] = set()
        exclude_translations: set[str] = set()

        if word in self.user_data.exclude_translations:
            exclude_translations = set(
                self.user_data.exclude_translations[word]
            )

        items: list[DictionaryItem] = self.dictionaries.get_items(word)

        if self.learning_language == GERMAN:
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
                    self.known_language,
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
                word, alternative_forms, self.learning_language
            )
            sentence_id: int = (
                sentences[index].sentence.id_ if index < len(sentences) else 0
            )

            # Preprocess answer.
            answer: str = self.learning_language.decode_text(answer)

            if answer == word:
                self.learning.register(
                    ResponseType.RIGHT, sentence_id, word, interval * 2
                )
                if items:
                    string_items: list[str] = [
                        x.to_str(self.known_language, self.interface)
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
                    self.user_data.exclude_sentence(word, sentence_id)
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/hide "):
                    self.user_data.exclude_translation(
                        word, " ".join(answer.split(" ")[1:])
                    )
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/btt "):
                    _, w, t = answer.split(" ")
                    self.user_data.exclude_translation(w, t)
                    continue

            if answer == "/no":

                self.interface.box(word)
                if items:
                    string_items: list[str] = [
                        x.to_str(self.known_language, self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                self.interface.box(word)

                new_answer = self.interface.input("Learn word? ")
                if not new_answer:
                    self.learning.register(
                        ResponseType.WRONG, sentence_id, word, SMALLEST_INTERVAL
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
