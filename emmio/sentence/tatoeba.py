import bz2
import json
import logging
import os
from dataclasses import dataclass, field
from os.path import join
from pathlib import Path

from emmio.language import Language
from emmio.sentence.core import Sentence, SentenceTranslations, Sentences
from emmio.sentence.database import SentenceDatabase
from emmio.ui import progress_bar
from emmio.user.data import UserData
from emmio.util import download

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class TatoebaSentences(Sentences):
    """Collection of sentences in two languages with translation relations."""

    path: Path
    language_1: Language
    language_2: Language
    database: SentenceDatabase

    links: dict[int, set[int]] = field(default_factory=dict)
    """
    Mapping form sentence identifiers in language 2 to sets of sentence
    identifiers in language 1.
    """

    def __post_init__(self):
        links_cache_path: Path = (
            self.path / "cache" / f"links_{self.language_1.get_part3()}_"
            f"{self.language_2.get_part3()}.json"
        )

        self.links: dict[int, set[int]] = {}

        if links_cache_path.is_file():
            self.read_link_sets(links_cache_path)
        else:
            self.read_links(self.path / "cache")
            logging.info("Caching links...")
            with open(links_cache_path, "w+") as output_file:
                content = {}
                for key in self.links:
                    assert isinstance(key, int)
                    content[key] = list(self.links[key])
                json.dump(content, output_file)

        self.cache: dict[str, list[int]] = {}

        links_cache_path: str = join(
            self.path / "cache", f"cache_{self.language_2.get_part3()}.json"
        )
        # FIXME: remove cache file.

        if os.path.isfile(links_cache_path):
            logging.info("Reading word cache...")
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
                    zip_path,
                )
            if zip_path.exists():
                with bz2.open(zip_path) as zip_file:
                    with file_path.open("wb+") as cache_file:
                        logging.info("Unzipping links file...")
                        cache_file.write(zip_file.read())

        logging.info("Reading links...")
        with file_path.open() as input_1:
            lines = input_1.readlines()

        links: dict[int, set[int]] = {}

        size = len(lines)

        logging.info(
            f"Caching links between {self.language_1.get_name()} and "
            f"{self.language_2.get_name()} Tatoeba sentences..."
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

        sentences_1: dict[str, Sentence] = self.database.get_sentences(
            self.language_1, cache_path
        )
        sentences_2: dict[str, Sentence] = self.database.get_sentences(
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
        logging.info("Reading link cache...")
        with file_name.open() as input_file:
            self.links = json.load(input_file)

    def fill_cache(self, file_name: str) -> None:
        """Construct dictionary from words to sentences."""
        logging.info("Fill word cache...")
        size = len(self.links)
        for index, id_ in enumerate(self.links.keys()):
            id_ = int(id_)
            progress_bar(index, size)
            word: str = ""
            sentence_words: set[str] = set()
            sentence: str = self.database.get_sentence(
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
            logging.info("Writing word cache...")
            json.dump(self.cache, output_file)

    def __len__(self):
        raise NotImplementedError()

    def filter_by_word(
        self,
        word: str,
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceTranslations]:
        """
        Get sentences that contain the specified word and their translations to
        the first language.

        :param word: word in the second language
        :param ids_to_skip: identifiers of sentences that should not be added to
            the result
        :param max_length: maximum sentence length
        :param max_number: maximum number of sentences to check
        """
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
            if str(id_) in self.links:
                result.append(
                    SentenceTranslations(
                        sentence,
                        [
                            self.database.get_sentence(self.language_1, x)
                            for x in self.links[str(id_)]
                        ],
                    )
                )
        return result

    def get_most_known(self, user_data: UserData) -> list[SentenceTranslations]:
        sentences: dict[str, Sentence] = self.database.get_sentences(
            self.language_2, self.path / "cache"
        )
        rates: list[tuple[str, float]] = []
        for sentence_id, sentence in sentences.items():
            words: list[str] = sentence.text.split(" ")
            rate: float = 0
            for word in words:
                word = word.lower()
                if (
                    word.endswith(".")
                    or word.endswith("?")
                    or word.endswith("։")
                ):
                    word = word[:-1]
                if user_data.is_known(word, self.language_2):
                    rate += 1
                else:
                    rate += 0
            if rate / len(words) > 0.9 and len(words) > 1:
                r = (rate + 1) / len(words)
                rates.append((sentence_id, r))

        for sentence_id, rate in sorted(rates, key=lambda x: -x[1]):
            text = self.database.get_sentence(self.language_2, sentence_id).text
            hidden: str = ""
            for c in text:
                if c not in " .?,":
                    hidden += "*"
                else:
                    hidden += c
            if str(sentence_id) in self.links and self.links[str(sentence_id)]:
                for sentence_id_2 in self.links[str(sentence_id)]:
                    print(
                        "   ",
                        self.database.get_sentence(
                            self.language_1, sentence_id_2
                        ).text,
                    )
                print(f"{rate:.2f} {hidden}")
                a = input()
                while a != text:
                    if a == "":
                        print(text)
                        break
                    a = input()
