import json
import os
import sqlite3

from dataclasses import dataclass
from datetime import timedelta
from iso639.iso639 import _Language as Language
from typing import Dict, List, Set
from os.path import join

from emmio.frequency import FrequencyDataBase
from emmio.language import symbols
from emmio.ui import progress_bar

FORMAT: str = "%Y.%m.%d %H:%M:%S.%f"
SMALLEST_INTERVAL: timedelta = timedelta(days=1)
RATIO: float = 2


@dataclass
class Sentence:
    id_: int
    text: str


@dataclass
class Translation:
    sentence: Sentence
    translations: List[Sentence]


class SentenceDataBase:
    """
    Database with tables:

    Tables <language>_sentences:
        ID: INTEGER, SENTENCE: TEXT
    """
    def __init__(self, data_base_file_name: str):
        sentence_db = sqlite3.connect(data_base_file_name)
        self.sentence_cursor = sentence_db.cursor()

    def get_sentence(self, language: Language, sentence_id: int) -> Sentence:
        """
        Get sentence by identifier.

        :param language: language of the sentence
        :param sentence_id: sentence unique integer identifier
        """
        table_id: str = f"{language.part1}_sentences"
        id_, text = self.sentence_cursor.execute(
            f"SELECT * FROM {table_id} WHERE id=?", (sentence_id, )).fetchone()
        return Sentence(id_, text)

    def get_sentences(self, language) -> Dict[str, Sentence]:
        result = {}
        table_id: str = f"{language.part1}_sentences"
        for row in self.sentence_cursor.execute(f"SELECT * FROM {table_id}"):
            id_, text = row
            result[id_] = Sentence(id_, text)
        return result


class Sentences:
    """ Collection of sentences. """
    def __init__(
            self, cache_directory_name: str, sentence_db: SentenceDataBase,
            frequency_db: FrequencyDataBase,
            language_1: Language, language_2: Language):

        self.frequency_db: FrequencyDataBase = frequency_db
        self.sentence_db: SentenceDataBase = sentence_db
        self.language_1: Language = language_1
        self.language_2: Language = language_2

        cache_file_name: str = (join(cache_directory_name,
            f"links_{self.language_1.part3}_{self.language_2.part3}.json"))

        self.links: Dict[int, Set[int]] = {}

        if os.path.isfile(cache_file_name):
            self.read_link_sets(cache_file_name)
        else:
            self.read_links(join(cache_directory_name, "links.csv"))
            print("Writing link cache...")
            with open(cache_file_name, "w+") as output_file:
                content = {}
                for key in self.links:
                    assert isinstance(key, int)
                    content[key] = list(self.links[key])
                json.dump(content, output_file)

        self.cache: Dict[str, List[int]] = {}

        cache_file_name: str = join(
            cache_directory_name, f"cache_{self.language_2.part3}.json")
        if os.path.isfile(cache_file_name):
            print("Reading word cache...")
            with open(cache_file_name) as input_file:
                self.cache = json.load(input_file)
        else:
            self.fill_cache(cache_file_name)

    def read_links(self, file_name: str):

        print("Reading links...")
        with open(file_name) as input_1:
            lines = input_1.readlines()

        links: Dict[int, Set[int]] = {}

        size = len(lines)

        for index, line in enumerate(lines):
            progress_bar(index, size)
            id_1, id_2 = map(int, line[:-1].split("\t"))
            if id_1 not in links and id_2 not in links:
                set_ = {id_1, id_2}
                links[id_1] = set_
                links[id_2] = set_
            if id_1 in links:
                set_ = links[id_1]
                set_.add(id_2)
                links[id_2] = set_
            if id_2 in links:
                set_ = links[id_2]
                set_.add(id_1)
                links[id_1] = set_
        progress_bar(-1, size)

        sentences_1 = self.sentence_db.get_sentences(self.language_1)
        sentences_2 = self.sentence_db.get_sentences(self.language_2)

        for id_1 in sentences_2:
            assert isinstance(id_1, int)
            self.links[id_1] = set()
            if id_1 in links:
                for id_2 in links[id_1]:
                    if id_2 in sentences_1:
                        self.links[id_1].add(id_2)
            if not self.links[id_1]:
                self.links.pop(id_1)

    def read_link_sets(self, file_name: str):
        print("Reading link cache...")
        with open(file_name) as input_file:
            self.links = json.load(input_file)

    def fill_cache(self, file_name: str) -> None:
        """ Construct dictionary from words to sentences. """
        print("Fill word cache...")
        size = len(self.links)
        for index, id_ in enumerate(self.links.keys()):  # type: int
            id_ = int(id_)
            progress_bar(index, size)
            word: str = ""
            sentence_words: Set[str] = set()
            sentence: str = self.sentence_db.get_sentence(
                self.language_2, id_).text
            for char in sentence.lower():  # type: str
                if char in symbols[self.language_2.part1]:
                    word += char
                else:
                    if word:
                        sentence_words.add(word)
                    word = ""
            if word:
                sentence_words.add(word)
            for word in sentence_words:  # type: str
                if word not in self.cache:
                    self.cache[word] = []
                self.cache[word].append(id_)
        progress_bar(-1, size)
        with open(file_name, "w+") as output_file:
            print("Writing word cache...")
            json.dump(self.cache, output_file)

    def filter_(self, word: str, ids_to_skip: Set[int]) -> List[Translation]:
        result: List[Translation] = []

        if word not in self.cache:
            return result

        for id_ in self.cache[word][:1000]:
            if id_ in ids_to_skip:
                continue
            id_: int
            sentence: Sentence = self.sentence_db.get_sentence(
                self.language_2, id_)
            index = sentence.text.lower().find(word)
            assert index >= 0
            if str(id_) in self.links:
                result.append(Translation(
                    sentence,
                    [self.sentence_db.get_sentence(self.language_1, x) for x in self.links[str(id_)]]))
        return result
