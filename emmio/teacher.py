"""
Teacher.
"""
import json
import math
import random
from datetime import timedelta
from pathlib import Path
from typing import Optional

from emmio.dictionary import Dictionaries, Dictionary, DictionaryItem
from emmio.frequency import FrequencyDatabase
from emmio.language import Language, construct_language, GERMAN
from emmio.learning import Learning, ResponseType
from emmio.lexicon import Lexicon, LexiconResponse
from emmio.sentence import SentenceDatabase, Sentences, Translation
from emmio.ui import log, Interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class Teacher:
    def __init__(
        self,
        cache_directory_name: Path,
        interface: Interface,
        sentence_db: SentenceDatabase,
        frequency_db: FrequencyDatabase,
        learning: Learning,
        lexicon: Lexicon,
        get_dictionaries=None,
    ) -> None:
        self.interface: Interface = interface
        self.known_language: Language = learning.language

        self.learning_language: Optional[Language]
        try:
            self.learning_language = construct_language(learning.subject)
        except KeyError:
            self.learning_language = None

        self.max_for_day: int = learning.ratio
        self.learning: Learning = learning
        self.dictionaries: list[Dictionary] = get_dictionaries(
            self.learning_language
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
                if word in self.sentences.cache and (
                    not self.learning.check_lexicon
                    or not self.lexicon
                    or not self.lexicon.has(word)
                    or self.lexicon.get(word) == LexiconResponse.DO_NOT_KNOW
                ):
                    for id_ in self.sentences.cache[word]:
                        if str(id_) in self.sentences.links:
                            self.words.append((index, word))
                            break

        with (Path("cache") / "exclude_sentences.json").open() as input_file:
            self.exclude_sentences = json.load(input_file)
        with (Path("cache") / "exclude_translations.json").open() as input_file:
            self.exclude_translations = json.load(input_file)

        self.skip = set()

    def start(self) -> bool:

        while True:
            word: Optional[str] = self.learning.get_next(self.skip)

            if word:
                code: str = self.learn(
                    word, self.learning.knowledges[word].interval, 0
                )
                self.learning.write()
                if code == "stop":
                    return False

                continue

            if self.learning.new_today() >= self.max_for_day:
                return True

            has_new_word: bool = False

            for index, word in self.words:
                if self.learning.has(word):
                    continue
                if word in self.skip:
                    continue

                if (
                    self.learning.check_lexicon
                    and self.lexicon.has(word)
                    and self.lexicon.get(word) != LexiconResponse.DO_NOT_KNOW
                ):
                    continue

                print(f"[{index}]")
                has_new_word = True

                if self.learning.ask_lexicon:
                    _, response, _ = self.lexicon.ask(
                        self.interface,
                        word,
                        [],
                        self.dictionaries,
                        log_name="log_ex",
                    )
                    self.lexicon.write()
                    if response != LexiconResponse.DO_NOT_KNOW:
                        continue

                code: str = self.learn(word, timedelta(), index)
                self.learning.write()
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
        if word in self.exclude_sentences:
            ids_to_skip = set(self.exclude_sentences[word])

        translations: list[Translation] = self.sentences.filter_(
            word, ids_to_skip, 120
        )
        if not translations:
            return "bad question"

        if interval.total_seconds() == 0:
            translations = sorted(
                translations, key=lambda x: len(x.sentence.text)
            )
        else:
            random.shuffle(translations)

        dictionaries: Dictionaries = Dictionaries(self.dictionaries)

        def print_sentence(show_index: bool = False, max_translations: int = 3):
            """
            Print sentence and its translations.

            :param show_index: show current sentence index
            :param max_translations: maximum number of translations to show
            """
            text: str = translations[index].sentence.text
            if show_index:
                text += f" ({index + 1}/{len(translations)})"

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
                if len(translations[index].translations) > i:
                    result += "\n" + translations[index].translations[i].text

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

        if word in self.exclude_translations:
            exclude_translations = self.exclude_translations[word]

        items: list[DictionaryItem] = dictionaries.get_items(word)

        if self.learning_language == GERMAN:
            for item in dictionaries.get_items(word[0].upper() + word[1:]):
                if item not in items:
                    items.append(item)

        words_to_hide: set[str] = set()
        for item in items:
            words_to_hide.add(item.word)
            for link in item.get_links():
                words_to_hide.add(link)

        if items:
            translation_list = [
                x.to_str(
                    self.known_language.get_code(),
                    self.interface,
                    False,
                    words_to_hide=words_to_hide,
                    hide_translations=exclude_translations,
                )
                for x in items
            ]
            self.interface.print(
                statistics + "\n" + "\n".join(translation_list)
            )
            alternative_forms: set[str] = items[0].get_links()
        else:
            self.interface.print(statistics + "\n" + "No translations.")

        print_sentence()

        while True:
            answer: str = self.interface.get_word(
                word, alternative_forms, self.learning_language
            )

            # Preprocess answer.
            answer: str = self.learning_language.decode_text(answer)

            if answer == word:
                self.learning.register(
                    ResponseType.RIGHT,
                    translations[index].sentence.id_,
                    word,
                    interval * 2,
                )
                if items:
                    string_items: list[str] = [
                        x.to_str(self.known_language.get_code(), self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                new_answer = self.interface.input(">>> ")
                while new_answer:
                    if new_answer == "s":
                        self.learning.register(
                            ResponseType.SKIP,
                            translations[index].sentence.id_,
                            word,
                            timedelta(),
                        )
                        break
                    new_answer = self.interface.input(">>> ")
                return "ok"

            if answer in ["s", "/skip"]:
                self.skip.add(word)
                return "ok"
            if answer == "/stop":
                return "stop"
            if answer.startswith("/b"):
                if answer == "/bs":
                    if word not in self.exclude_sentences:
                        self.exclude_sentences[word] = []
                    self.exclude_sentences[word].append(
                        translations[index].sentence.id_
                    )
                    with (Path("cache") / "exclude_sentences.json").open(
                        "w+"
                    ) as output_file:
                        json.dump(self.exclude_sentences, output_file)
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/bt "):
                    if word not in self.exclude_translations:
                        self.exclude_translations[word] = []
                    _, t = answer.split(" ")
                    self.exclude_translations[word].append(t)
                    with (Path("cache") / "exclude_translations.json").open(
                        "w+"
                    ) as output_file:
                        json.dump(self.exclude_translations, output_file)
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/btt "):
                    _, w, t = answer.split(" ")
                    if w not in self.exclude_translations:
                        self.exclude_translations[w] = []
                    self.exclude_translations[w].append(t)
                    with open("exclude_translations.json", "w+") as output_file:
                        json.dump(self.exclude_translations, output_file)
                    continue
            if answer == "n":

                self.interface.box(word)
                if items:
                    string_items: list[str] = [
                        x.to_str(self.known_language.get_code(), self.interface)
                        for x in items
                    ]
                    self.interface.print("\n".join(string_items))
                self.interface.box(word)

                new_answer = self.interface.input("Learn word? ")
                if not new_answer:
                    self.learning.register(
                        ResponseType.WRONG,
                        translations[index].sentence.id_,
                        word,
                        SMALLEST_INTERVAL,
                    )
                else:
                    self.learning.register(
                        ResponseType.SKIP,
                        translations[index].sentence.id_,
                        word,
                        timedelta(),
                    )
                return "ok"
            if answer == "":
                index += 1
                if index >= len(translations):
                    self.interface.print("No more sentences.")
                    index -= 1
                else:
                    print_sentence()
