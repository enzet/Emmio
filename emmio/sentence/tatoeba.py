"""Tatoeba sentences.

See https://tatoeba.org/
"""

import bz2
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import override

from tqdm import tqdm

from emmio.language import Language
from emmio.sentence.core import (
    Sentence,
    SentenceElement,
    Sentences,
    SentenceTranslations,
    split_sentence,
)
from emmio.sentence.database import SentenceDatabase
from emmio.util import download

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class TatoebaSentences(Sentences):
    """Collection of sentences in two languages from Tatoeba project.

    See https://tatoeba.org/
    """

    path: Path
    language_1: Language
    language_2: Language
    database: SentenceDatabase

    links: dict[int, set[int]] = field(default_factory=dict)
    """Mapping between sentences.

    Mapping from sentence identifiers in language 2 to sets of sentence
    identifiers in language 1. Meaning that these sentences are translations.
    E.g. `1 -> {2, 3}`, where `1` is `You have a book` and `2` and `3` are
    `Du hast ein Buch` and `Sie haben ein Buch` respectively.

    Cache for links are in
    `<path>/cache/links_<language 1 code>_<language 2 code>.json`.
    """

    cache: dict[str, list[int]] = field(default_factory=dict)
    """Mapping from words to sentences.

    Mapping from words to lists of identifiers of sentences that contain these
    words. E.g. `book -> [1, 2]`, where `1` is `I have a book` and `2` is
    `You have a book`.

    Cache for words are in `<path>/cache/cache_<language 2 code>.json`.
    """

    def __post_init__(self) -> None:
        """Fill links and cache."""

        links_cache_path: Path = (
            self.path / "cache" / f"links_{self.language_1.get_part3()}_"
            f"{self.language_2.get_part3()}.json"
        )
        if links_cache_path.is_file():
            self.read_link_sets(links_cache_path)
        else:
            self.read_links(self.path / "cache")
            logging.info("Caching links...")
            with links_cache_path.open("w+", encoding="utf-8") as output_file:
                content: dict[int, list[int]] = {}
                for key, value in self.links.items():
                    assert isinstance(key, int)
                    content[key] = list(value)
                json.dump(content, output_file)

        word_cache_path: Path = (
            self.path / "cache" / f"cache_{self.language_2.get_part3()}.json"
        )
        # FIXME: remove cache file.

        if os.path.isfile(word_cache_path):
            logging.info("Reading word cache...")
            with word_cache_path.open(encoding="utf-8") as input_file:
                self.cache = json.load(input_file)
        else:
            self.fill_cache(word_cache_path)

    def read_links(self, cache_path: Path) -> None:
        """Read links from a cache file.

        :param cache_path: path to the cache directory
        """
        file_path: Path = cache_path / "links.csv"

        if not file_path.exists():
            zip_path: Path = cache_path / "links.tar.bz2"
            # FIXME: remove zip file.
            if not zip_path.exists():
                download(
                    "https://downloads.tatoeba.org/exports/links.tar.bz2",
                    zip_path,
                )
            if zip_path.exists():
                with bz2.open(zip_path) as zip_file:
                    with file_path.open("wb+") as cache_file:
                        logging.info("Unzipping links file...")
                        cache_file.write(zip_file.read())

        logging.info(
            "Reading links from `links.csv` between `%s` and `%s`...",
            self.language_1.get_name(),
            self.language_2.get_name(),
        )
        with file_path.open(encoding="utf-8") as input_1:
            lines = input_1.readlines()

        links: dict[int, set[int]] = {}

        logging.info(
            "Caching links between `%s` and `%s` Tatoeba sentences...",
            self.language_1.get_name(),
            self.language_2.get_name(),
        )
        for line in tqdm(lines):
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

        sentences_1: dict[int, Sentence] = self.database.get_sentences(
            self.language_1, cache_path
        )
        sentences_2: dict[int, Sentence] = self.database.get_sentences(
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

    def read_link_sets(self, file_name: Path) -> None:
        """Read link cache from a JSON file."""

        logging.info("Reading link cache...")
        with file_name.open(encoding="utf-8") as input_file:
            links: dict[str, list[int]] = json.load(input_file)

        # JSON file may contain only string keys, so we need to convert them to
        # integers.
        for key, value in links.items():
            self.links[int(key)] = set(value)

    def fill_cache(self, file_name: Path) -> None:
        """Construct dictionary from words to sentences.

        Split all sentences into words and construct a dictionary from words to
        sentences containing these words.
        """
        logging.info("Fill word cache...")

        for id_ in tqdm(self.links.keys()):
            id_ = int(id_)
            sentence: str = self.database.get_sentence(
                self.language_2, id_
            ).text

            parts: list[tuple[str, SentenceElement]] = split_sentence(
                sentence, self.language_2
            )
            for part, type_ in parts:
                if type_ == SentenceElement.WORD:
                    normalized = self.language_2.normalize(part)
                    if normalized not in self.cache:
                        self.cache[normalized] = []
                    self.cache[normalized].append(id_)

        with file_name.open("w+", encoding="utf-8") as output_file:
            logging.info("Writing word cache...")
            json.dump(self.cache, output_file)

    @override
    def filter_by_word(
        self,
        word: str,
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceTranslations]:

        result: list[SentenceTranslations] = []

        if word not in self.cache:
            logging.debug("Word is not in cache.")
            return result

        ids_to_check: list[int] = (
            self.cache[word]
            if max_number is None
            else self.cache[word][:max_number]
        )
        for id_ in ids_to_check:
            if id_ in ids_to_skip:
                continue
            sentence: Sentence = self.database.get_sentence(
                self.language_2, id_
            )
            if len(sentence.text) > max_length:
                continue
            index = sentence.text.lower().find(word)
            assert index >= 0
            if id_ in self.links:
                result.append(
                    SentenceTranslations(
                        sentence,
                        [
                            self.database.get_sentence(self.language_1, x)
                            for x in self.links[id_]
                        ],
                    )
                )
        return result

    @override
    def filter_by_word_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceTranslations]]:

        return Sentences.rate(
            is_known,
            self.filter_by_word(word, ids_to_skip, max_length, max_number),
            self.language_2,
        )
