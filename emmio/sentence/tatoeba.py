"""Tatoeba sentences.

Tatoeba is a project that provides a database of sentences in many languages.

See https://tatoeba.org/
"""

import bz2
import json
import logging
from collections.abc import Callable
from pathlib import Path

from tqdm import tqdm

from emmio.language import Language
from emmio.sentence.core import (
    Sentence,
    SentenceElement,
    Sentences,
    SentenceAndTranslations,
    split_sentence,
)
from emmio.sentence.database import TatoebaDatabase
from emmio.util import download

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class TatoebaSentences(Sentences):
    """Collection of sentences in two languages from Tatoeba project.

    See https://tatoeba.org/
    """

    links: dict[int, set[int]]
    """Mapping between sentences.

    Mapping from sentence identifiers in language 2 to sets of sentence
    identifiers in language 1. Meaning that these sentences are translations.
    E.g. `1 -> {2, 3}`, where `1` is `You have a book` and `2` and `3` are
    `Du hast ein Buch` and `Sie haben ein Buch` respectively.

    Cache for links are in
    `<path>/cache/links_<language 1 code>_<language 2 code>.json`.
    """

    cache_path: Path
    """Path to the cache directory."""

    def __init__(self, path: Path, database: TatoebaDatabase) -> None:
        """Fill links and cache."""

        self.path: Path = path
        """Path to the directory with the sentences."""

        self.database: TatoebaDatabase = database
        """Database of sentences."""

        self.cache_path: Path = self.path / "cache"

        self.word_cache: dict[Language, dict[str, list[int]]] = {}
        """Word cache for each language.
    
        Mapping from words to lists of identifiers of sentences that contain
        these words. E.g. `book -> [1, 2]`, where `1` is `I have a book` and `2`
        is `You have a book`.

        Cache for words are in `<path>/cache/words_<language 2 code>.json`.
        """

        # FIXME: implement.
        self.ids_to_skip: set[int] = set()

    def read_word_cache(self, language: Language) -> dict[str, list[int]]:
        """Read word cache from a JSON file."""

        if language in self.word_cache:
            return self.word_cache[language]

        word_cache_path: Path = (
            self.cache_path / f"words_{language.get_part3()}.json"
        )
        if word_cache_path.is_file():
            logging.info(
                "Reading word to Tatoeba sentence cache for `%s`...",
                language.get_name(),
            )
            with word_cache_path.open(encoding="utf-8") as input_file:
                self.word_cache[language] = json.load(input_file)
                return self.word_cache[language]
        else:
            word_to_sentence_id: dict[str, list[int]] = self.create_word_cache(
                word_cache_path, language
            )
            self.word_cache[language] = word_to_sentence_id
            return word_to_sentence_id

    def read_links__(self, cache_path: Path, language_1: Language, language_2: Language) -> None:
        """Read links from a cache file.

        :param cache_path: path to the cache directory
        """
        logging.info(
            "Reading links from `links.csv` between `%s` and `%s`...",
            language_1.get_name(),
            language_2.get_name(),
        )
        with links_csv_path.open(encoding="utf-8") as input_csv:
            lines = input_csv.readlines()

        # Links only between sentences in `language_1` and `language_2`.
        links: dict[int, set[int]] = {}

        logging.info(
            "Caching links between `%s` and `%s` Tatoeba sentences...",
            language_1.get_name(),
            language_2.get_name(),
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
            language_1, cache_path
        )
        sentences_2: dict[int, Sentence] = self.database.get_sentences(
            language_2, cache_path
        )
        for id_1 in sentences_2:
            self.links[id_1] = set()
            if id_1 in links:
                for id_2 in links[id_1]:
                    if id_2 in sentences_1:
                        self.links[id_1].add(id_2)
            if not self.links[id_1]:
                self.links.pop(id_1)

    def read_links(self, file_name: Path) -> dict[int, set[int]]:
        """Read link cache from a JSON file."""

        logging.info("Reading link cache...")
        with file_name.open(encoding="utf-8") as input_file:
            data: dict[str, list[int]] = json.load(input_file)

        # JSON file may contain only string keys, so we need to convert them to
        # integers.
        links: dict[int, set[int]] = {}
        for key, value in data.items():
            links[int(key)] = set(value)
        return links

    def get_cached_links(self, language: Language) -> dict[int, set[int]]:
        """Get cached links for a language."""

        # If links for the language are in memory, return them.
        if language in self.links:
            return self.links[language]

        links: dict[int, set[int]] = {}

        # If links for the language are in cache, read them.
        cache_file_path: Path = self.cache_path / f"links_{language.get_part3()}.bin"
        if cache_file_path.is_file():
            with cache_file_path.open("rb") as input_file:
                from_: int = int.from_bytes(input_file.read(4), "big")
                to_: int = int.from_bytes(input_file.read(4), "big")
                if from_ not in links:
                    links[from_] = set()
                links[from_].add(to_)
            self.links[language] = links
            return links

        links_csv_path: Path = self.cache_path / "links.csv"

        # If links file doesn't exist in cache, download and unzip it.
        if not links_csv_path.exists():

            # Download zipped links file if it doesn't exist in cache.
            links_zip_path: Path = self.cache_path / "links.tar.bz2"
            if not links_zip_path.exists():
                download(
                    "https://downloads.tatoeba.org/exports/links.tar.bz2",
                    links_zip_path,
                )

            # Unzip links file to `links.csv`.
            if links_zip_path.exists():
                with bz2.open(links_zip_path) as zip_file:
                    with links_csv_path.open("wb+") as cache_file:
                        logging.info("Unzipping links file...")
                        cache_file.write(zip_file.read())
            else:
                raise Exception("Failed to download links file.")

            # Remove zipped links file.
            links_zip_path.unlink()

        with links_csv_path.open(encoding="utf-8") as input_csv:
            lines = input_csv.readlines()

        links: dict[int, set[int]] = {}
        for line in lines:
            from_, to_ = map(int, line[:-1].split("\t"))
            if from_ in self.get_

        return links

    def create_word_cache(self, file_name: Path, language: Language) -> dict[str, list[int]]:
        """Construct dictionary from words to sentences.

        Split all sentences into words and construct a dictionary from words to
        sentences containing these words.
        """
        logging.info(
            "Create word to Tatoeba sentence cache for `%s`...",
            language.get_name(),
        )
        word_to_sentence_id: dict[str, list[int]] = {}

        for id_ in tqdm(self.get_cached_links(language).keys()):
            sentence: str = self.get_sentence(language, id_).text

            parts: list[tuple[str, SentenceElement]] = split_sentence(
                sentence, language
            )
            for part, type_ in parts:
                if type_ == SentenceElement.WORD:
                    normalized = language.normalize(part)
                    if normalized not in word_to_sentence_id:
                        word_to_sentence_id[normalized] = []
                    word_to_sentence_id[normalized].append(id_)

        with file_name.open("w+", encoding="utf-8") as output_file:
            logging.info("Writing word cache...")
            json.dump(word_to_sentence_id, output_file)

        return word_to_sentence_id

    def get_sentence(self, language: Language, id_: int) -> Sentence:
        """Get a sentence by its identifier."""

        return self.database.get_sentence(language, id_)

    def get_by_word(
        self,
        word: str,
        language: Language,
        translation_languages: list[Language],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceAndTranslations]:
        """Get sentences containing a word.

        :param word: word to be presented in the resulting sentences
        :param language: language of the sentences
        :param translation_languages: languages of translations
        :param max_length: maximum length of the sentence to include
        :param max_number: maximum size of the resulting list
        """
        result: list[SentenceAndTranslations] = []

        word_to_sentence_id: dict[str, list[int]] = self.read_word_cache(language)
        if word not in word_to_sentence_id:
            logging.debug("Tatoeba has no sentences with the word.")
            return result

        cached_links: dict[int, list[int]] = self.get_cached_links(language)

        # Identifiers of sentences in main language.
        sentence_ids: list[int] = (
            word_to_sentence_id[word]
            if max_number is None
            else word_to_sentence_id[word][:max_number]
        )

        for id_ in sentence_ids:
            if id_ in self.ids_to_skip:
                continue

            sentence: Sentence = self.get_sentence(language, id_)
            if len(sentence.text) > max_length:
                continue

            # If there are no translation languages or the sentence has no
            # translations, return just sentences.
            if not translation_languages or id_ not in cached_links:
                result.append(SentenceAndTranslations(sentence, language, {}))
                continue

            translations: dict[Language, list[Sentence]] = {
                translation_language: []
                for translation_language in translation_languages
            }

            translation_ids: list[int] = cached_links[id_]

            for translation_language in translation_languages:
                for translation_id in translation_ids:
                    if translation_id in self.get_cached_links(translation_language).keys():
                        translations[translation_language].append(
                            self.get_sentence(translation_language, translation_id)
                        )

            result.append(
                SentenceAndTranslations(sentence, language, translations)
            )
        return result

    def filter_by_word_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceAndTranslations]]:

        return Sentences.rate(
            is_known,
            self.filter_by_word(word, ids_to_skip, max_length, max_number),
            self.language_2,
        )
