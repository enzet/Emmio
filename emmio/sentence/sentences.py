import bz2
import json
import os
from os.path import join
from pathlib import Path
from typing import Dict, Set, List, Optional

from emmio.language import Language
from emmio.sentence.core import Sentence, Translation
from emmio.sentence.database import SentenceDatabase
from emmio.ui import log, progress_bar
from emmio.util import download


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
        self,
        word: str,
        ids_to_skip: Set[int],
        max_length: int,
        max_number: Optional[int] = 1000,
    ) -> List[Translation]:
        """
        Get sentences that contain the specified word and their translations to
        the second language.

        :param word: word in the first language
        :param ids_to_skip: identifiers of sentences that should not be added to
            the result
        :param max_length: maximum sentence length
        :param max_number: maximum number of sentences to check
        """
        result: List[Translation] = []

        if word not in self.cache:
            return result

        ids_to_check: list[int] = (
            self.cache[word]
            if max_number is None
            else self.cache[word][:max_number]
        )
        for id_ in ids_to_check:
            if id_ in ids_to_skip:
                continue
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
