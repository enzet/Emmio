import bz2
import json
import os
from dataclasses import dataclass
from os.path import join
from pathlib import Path
from typing import Dict, List, Set

from emmio.database import Database
from emmio.language import Language
from emmio.ui import log, progress_bar
from emmio.util import download

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


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

    def create(self, language: Language, cache_path: Path):
        table_id: str = f"{language.language.part1}_sentences"
        file_path = cache_path / f"{language.get_part3()}_sentences.tsv"

        if not file_path.exists():
            zip_path: Path = (
                cache_path / f"{language.get_part3()}_sentences.tsv.bz2"
            )
            # FIXME: remove zip file.
            if not zip_path.is_file():
                download(
                    f"https://downloads.tatoeba.org/exports/per_language/"
                    f"{language.get_part3()}/{language.get_part3()}"
                    f"_sentences.tsv.bz2",
                    zip_path,
                )
            with bz2.open(zip_path) as zip_file:
                with file_path.open("wb+") as cache_file:
                    log(f"unzipping sentences for {language.get_name()}")
                    cache_file.write(zip_file.read())

        self.cursor.execute(
            f"CREATE TABLE {table_id} (id integer primary key, sentence text)"
        )
        print(f"Reading {table_id}...")
        with file_path.open() as input_file:
            for line in input_file.readlines():
                id_, _, sentence = line[:-1].split("\t")
                self.cursor.execute(
                    f"INSERT INTO {table_id} VALUES (?,?)", (id_, sentence)
                )
        self.connection.commit()

    def get_sentence(self, language: Language, sentence_id: int) -> Sentence:
        """
        Get sentence by identifier.

        :param language: language of the sentence
        :param sentence_id: sentence unique integer identifier
        """
        table_id: str = f"{language.get_code()}_sentences"
        id_, text = self.cursor.execute(
            f"SELECT * FROM {table_id} WHERE id=?", (sentence_id,)
        ).fetchone()
        return Sentence(id_, text)

    def get_sentences(
        self, language: Language, cache_path: Path
    ) -> dict[str, Sentence]:
        """Get all sentences written in the specified language."""
        result = {}
        table_id: str = f"{language.get_code()}_sentences"
        if not self.has_table(table_id):
            self.create(language, cache_path)
        for row in self.cursor.execute(f"SELECT * FROM {table_id}"):
            id_, text = row
            result[id_] = Sentence(id_, text)
        return result


class Sentences:
    """Collection of sentences."""

    def __init__(
        self,
        cache_path: Path,
        sentence_db: SentenceDatabase,
        language_1: Language,
        language_2: Language,
    ):

        self.sentence_db: SentenceDatabase = sentence_db
        self.language_1: Language = language_1
        self.language_2: Language = language_2

        links_cache_path: Path = (
            cache_path / f"links_{self.language_1.get_part3()}_"
            f"{self.language_2.get_part3()}.json"
        )

        self.links: Dict[int, Set[int]] = {}

        if links_cache_path.is_file():
            self.read_link_sets(links_cache_path)
        else:
            self.read_links(cache_path)
            log("writing link cache")
            with open(links_cache_path, "w+") as output_file:
                content = {}
                for key in self.links:
                    assert isinstance(key, int)
                    content[key] = list(self.links[key])
                json.dump(content, output_file)

        self.cache: Dict[str, List[int]] = {}

        links_cache_path: str = join(
            cache_path, f"cache_{self.language_2.get_part3()}.json"
        )
        # FIXME: remove cache file.

        if os.path.isfile(links_cache_path):
            log("reading word cache")
            with open(links_cache_path) as input_file:
                self.cache = json.load(input_file)
        else:
            self.fill_cache(links_cache_path)

    def read_links(self, cache_path: Path):

        file_path: Path = cache_path / "links.csv"

        if not file_path.exists():
            zip_path: Path = cache_path / "links.tar.bz2"
            # FIXME: remove zip file.
            if not zip_path.exists():
                download(
                    "https://downloads.tatoeba.org/exports/links.tar.bz2",
                    Path("links.tar.bz2"),
                )
            with bz2.open(zip_path) as zip_file:
                with file_path.open("wb+") as cache_file:
                    log("unzipping links")
                    cache_file.write(zip_file.read())

        log("reading links")
        with file_path.open() as input_1:
            lines = input_1.readlines()

        links: Dict[int, Set[int]] = {}

        size = len(lines)

        log(
            f"construct cache links for {self.language_1.get_name()} and "
            f"{self.language_2.get_name()}"
        )
        for index, line in enumerate(lines):
            progress_bar(index, size)

            try:
                id_1, id_2 = map(int, line[:-1].split("\t"))
            except ValueError:
                continue

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

        sentences_1: dict[str, Sentence] = self.sentence_db.get_sentences(
            self.language_1, cache_path
        )
        sentences_2: dict[str, Sentence] = self.sentence_db.get_sentences(
            self.language_2, cache_path
        )

        for id_1 in sentences_2:
            assert isinstance(id_1, int)
            self.links[id_1] = set()
            if id_1 in links:
                for id_2 in links[id_1]:
                    if id_2 in sentences_1:
                        self.links[id_1].add(id_2)
            if not self.links[id_1]:
                self.links.pop(id_1)

    def read_link_sets(self, file_name: Path):

        log("reading link cache")
        with file_name.open() as input_file:
            self.links = json.load(input_file)

    def fill_cache(self, file_name: str) -> None:
        """Construct dictionary from words to sentences."""
        log("fill word cache")
        size = len(self.links)
        for index, id_ in enumerate(self.links.keys()):
            id_ = int(id_)
            progress_bar(index, size)
            word: str = ""
            sentence_words: Set[str] = set()
            sentence: str = self.sentence_db.get_sentence(
                self.language_2, id_
            ).text
            for symbol in sentence.lower():
                if self.language_2.has_symbol(symbol):
                    word += symbol
                else:
                    if word:
                        sentence_words.add(word)
                    word = ""
            if word:
                sentence_words.add(word)
            for word in sentence_words:
                if word not in self.cache:
                    self.cache[word] = []
                self.cache[word].append(id_)
        progress_bar(-1, size)
        with open(file_name, "w+") as output_file:
            log("writing word cache")
            json.dump(self.cache, output_file)

    def filter_(
        self, word: str, ids_to_skip: Set[int], max_length: int
    ) -> List[Translation]:
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
                self.language_2, id_
            )
            if len(sentence.text) > max_length:
                continue
            index = sentence.text.lower().find(word)
            assert index >= 0
            if str(id_) in self.links:
                result.append(
                    Translation(
                        sentence,
                        [
                            self.sentence_db.get_sentence(self.language_1, x)
                            for x in self.links[str(id_)]
                        ],
                    )
                )
        return result
