import json
import os
from dataclasses import dataclass
from os.path import join
from typing import Dict, List, Set

from emmio.database import Database
from emmio.language import Language
from emmio.ui import log, progress_bar


@dataclass
class Sentence:
    """
    Some part of a text written in a single language.  Sometimes it may contain
    two or more sentences or not be complete in itself.
    """
    id_: int
    text: str


@dataclass
class Translation:
    """
    Some part of a text written in a single language and its translations to
    other languages.  Some translations may be transitive.
    """
    sentence: Sentence
    translations: List[Sentence]


class SentenceDatabase(Database):
    """
    Database with tables:

    Tables <language>_sentences:
        ID: INTEGER, SENTENCE: TEXT
    """
    def get_sentence(self, language: Language, sentence_id: int) -> Sentence:
        """
        Get sentence by identifier.

        :param language: language of the sentence
        :param sentence_id: sentence unique integer identifier
        """
        table_id: str = f"{language.get_code()}_sentences"
        id_, text = self.cursor.execute(
            f"SELECT * FROM {table_id} WHERE id=?", (sentence_id, )).fetchone()
        return Sentence(id_, text)

    def get_sentences(self, language: Language) -> Dict[str, Sentence]:
        """ Get all sentences written in the specified language. """
        result = {}
        table_id: str = f"{language.get_code()}_sentences"
        for row in self.cursor.execute(f"SELECT * FROM {table_id}"):
            id_, text = row
            result[id_] = Sentence(id_, text)
        return result


class Sentences:
    """ Collection of sentences. """
    def __init__(
            self, cache_directory_name: str, sentence_db: SentenceDatabase,
            language_1: Language, language_2: Language):

        self.sentence_db: SentenceDatabase = sentence_db
        self.language_1: Language = language_1
        self.language_2: Language = language_2

        cache_file_name: str = (join(
            cache_directory_name,
            f"links_{self.language_1.get_part3()}_"
            f"{self.language_2.get_part3()}.json"))

        self.links: Dict[int, Set[int]] = {}

        if os.path.isfile(cache_file_name):
            self.read_link_sets(cache_file_name)
        else:
            self.read_links(join(cache_directory_name, "links.csv"))
            log("writing link cache")
            with open(cache_file_name, "w+") as output_file:
                content = {}
                for key in self.links:
                    assert isinstance(key, int)
                    content[key] = list(self.links[key])
                json.dump(content, output_file)

        self.cache: Dict[str, List[int]] = {}

        cache_file_name: str = join(
            cache_directory_name, f"cache_{self.language_2.get_part3()}.json")
        if os.path.isfile(cache_file_name):
            log("reading word cache")
            with open(cache_file_name) as input_file:
                self.cache = json.load(input_file)
        else:
            self.fill_cache(cache_file_name)

    def read_links(self, file_name: str):

        log("reading links")
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
        log("reading link cache")
        with open(file_name) as input_file:
            self.links = json.load(input_file)

    def fill_cache(self, file_name: str) -> None:
        """ Construct dictionary from words to sentences. """
        log("fill word cache")
        size = len(self.links)
        for index, id_ in enumerate(self.links.keys()):
            id_ = int(id_)
            progress_bar(index, size)
            word: str = ""
            sentence_words: Set[str] = set()
            sentence: str = self.sentence_db.get_sentence(
                self.language_2, id_).text
            for symbol in sentence.lower():  # type: str
                if self.language_2.has_symbol(symbol):
                    word += symbol
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
            log("writing word cache")
            json.dump(self.cache, output_file)

    def filter_(
            self, word: str, ids_to_skip: Set[int],
            max_length: int) -> List[Translation]:
        """
        Get sentences that contain the specified word and their translations to
        the second language.

        :param word: word in the first language
        :param ids_to_skip: identifiers of sentences that should not be added to
            the result
        :param max_length: maximum sentence length
        """
        result: List[Translation] = []

        if word not in self.cache:
            return result

        for id_ in self.cache[word][:1000]:
            if id_ in ids_to_skip:
                continue
            id_: int
            sentence: Sentence = self.sentence_db.get_sentence(
                self.language_2, id_)
            if len(sentence.text) > max_length:
                continue
            index = sentence.text.lower().find(word)
            assert index >= 0
            if str(id_) in self.links:
                result.append(Translation(
                    sentence,
                    [self.sentence_db.get_sentence(self.language_1, x)
                     for x in self.links[str(id_)]]))
        return result
