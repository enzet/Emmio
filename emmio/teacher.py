import json
import math
import random
from datetime import timedelta
from typing import List, Tuple, Optional, Set

from iso639 import languages
from iso639.iso639 import _Language as Language

from emmio.dictionary import Dictionary, Dictionaries
from emmio.frequency import FrequencyDataBase
from emmio.language import symbols, decode_esperanto
from emmio.learning import Learning, ResponseType
from emmio.lexicon import Lexicon, LexiconResponse
from emmio.sentence import (
    SentenceDataBase, Sentences, Translation, SMALLEST_INTERVAL)
from emmio.ui import get_word, box


class Teacher:
    def __init__(
            self, cache_directory_name: str, sentence_db: SentenceDataBase,
            frequency_db: FrequencyDataBase, learning: Learning,
            get_dictionaries=None):

        self.language_1: Language = learning.language

        self.language_2: Language
        try:
            self.language_2 = languages.get(part1=learning.subject)
        except KeyError:
            self.language_2 = None

        self.max_for_day = learning.ratio
        self.sentences_db = sentence_db
        self.frequency_db = frequency_db
        self.learning = learning
        self.dictionaries: List[Dictionary] = get_dictionaries(
            self.language_2.part1)

        self.lexicon = Lexicon(
            self.language_2.part1,
            f"../Emmio-dev/lexicon/enzet_{self.language_2.part1}.json")

        self.sentences: Sentences = Sentences(
            cache_directory_name, sentence_db, frequency_db, self.language_1,
            self.language_2)

        self.words: List[Tuple[int, str]] = []
        print("Getting words...")
        for index, word, _ in self.frequency_db.get_words(self.language_2):
            if (word in self.sentences.cache
                    and (not self.learning.check_lexicon or
                         not self.lexicon or
                         not self.lexicon.has(word) or
                         self.lexicon.get(word) == LexiconResponse.DO_NOT_KNOW)):
                for id_ in self.sentences.cache[word]:
                    if str(id_) in self.sentences.links:
                        self.words.append((index, word))
                        break

        with open("exclude_sentences.json") as input_file:
            self.exclude_sentences = json.load(input_file)
        with open("exclude_translations.json") as input_file:
            self.exclude_translations = json.load(input_file)

        self.skip = set()

    def start(self) -> bool:
        while True:
            word: Optional[str] = self.learning.get_next(self.skip)
            if word:
                proceed: bool = self.learn(
                    word, self.learning.knowledges[word].interval, 0)
                self.learning.write()
                if not proceed:
                    return False
            else:
                if self.learning.new_today() >= self.max_for_day:
                    return True
                has_new_word = False
                for index, word in self.words:
                    if not self.learning.has(word) and word not in self.skip:
                        has_new_word = True
                        proceed: bool = self.learn(word, timedelta(), index)
                        self.learning.write()
                        if not proceed:
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
                    word, self.learning.knowledges[word].interval, 0)
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

        ids_to_skip: Set[int] = set()
        if word in self.exclude_sentences:
            ids_to_skip = set(self.exclude_sentences[word])

        translations: List[Translation] = self.sentences.filter_(
            word, ids_to_skip)
        if not translations:
            return "bad question"

        if interval.total_seconds() == 0:
            translations = sorted(
                translations, key=lambda x: len(x.sentence.text))
        else:
            random.shuffle(translations)

        dictionaries = Dictionaries(self.language_1, self.dictionaries)

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
            for position, char in enumerate(text):  # type: str
                if char.lower() in symbols[self.language_2.part1]:
                    w += char
                else:
                    if w:
                        if w.lower() == word:
                            result += "░" * len(word)
                        else:
                            result += w
                    result += char
                    w = ""

            print(result)
            for i in range(max_translations):
                if len(translations[index].translations) > i:
                    print(translations[index].translations[i].text)

        def log_(interval):
            if interval.total_seconds() == 0:
                return 0
            return int(math.log(interval.total_seconds() / 60 / 60 / 24, 2)) + 1

        index: int = 0
        s = ""
        if interval.total_seconds() > 0:
            s += f"{'◕ ' * log_(interval)} "
        else:
            s += f"frequency index: {word_index}  "
        s += (
            f"new today: {self.learning.new_today()}  "
            f"to repeat: {self.learning.to_repeat()}")
        print(s)

        exclude_translations: Set[str] = set()
        if word in self.exclude_translations:
            exclude_translations = self.exclude_translations[word]
        translation = dictionaries.get_translation(
            word, False, exclude_translations)
        if translation:
            print(translation)

        print_sentence()

        while True:
            answer: str = get_word(word, self.language_2)
            if self.language_2 == languages.get(part1="eo"):
                answer = decode_esperanto(answer)
            if answer == word:
                self.learning.register(
                    ResponseType.RIGHT, translations[index].sentence.id_, word,
                    interval * 2)
                translation = dictionaries.get_translation(word)
                if translation:
                    print(translation)
                new_answer = input(">>> ")
                while new_answer:
                    if new_answer == "s":
                        self.learning.register(
                            ResponseType.SKIP, translations[index].sentence.id_,
                            word, timedelta())
                        break
                    new_answer = input(">>> ")
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
                        translations[index].sentence.id_)
                    with open("exclude_sentences.json", "w+") as output_file:
                        json.dump(self.exclude_sentences, output_file)
                    self.skip.add(word)
                    return "ok"
                elif answer.startswith("/bt "):
                    if word not in self.exclude_translations:
                        self.exclude_translations[word] = []
                    _, t = answer.split(" ")
                    self.exclude_translations[word].append(t)
                    with open("exclude_translations.json", "w+") as output_file:
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
                print(box(word))
                translation = dictionaries.get_translation(word)
                if translation:
                    print(translation)
                new_answer = input("Learn word? ")
                if not new_answer:
                    self.learning.register(
                        ResponseType.WRONG, translations[index].sentence.id_,
                        word, SMALLEST_INTERVAL)
                else:
                    self.learning.register(
                        ResponseType.SKIP, translations[index].sentence.id_,
                        word, timedelta())
                return "ok"
            if answer == "":
                index += 1
                if index >= len(translations):
                    print("No more sentences.")
                    index -= 1
                else:
                    print_sentence()