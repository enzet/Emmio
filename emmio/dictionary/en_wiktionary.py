"""Gate for English Wiktionary service.

See https://en.wiktionary.org.
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Any, override

import requests
from tqdm import tqdm

from emmio.dictionary.core import (
    Definition,
    DefinitionValue,
    Dictionary,
    DictionaryItem,
    Form,
    Link,
)
from emmio.language import KnownLanguages, Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

# Languages whose kaikki.org name differs from Emmio's `get_name()`, keyed by
# ISO 639-1 code. Without these, the words-file URL would 404.
_KAIKKI_NAME_OVERRIDES: dict[str, str] = {
    "el": "Greek",  # Emmio: "Modern Greek".
    "si": "Sinhalese",  # Emmio: "Sinhala".
    "sl": "Slovene",  # Emmio: "Slovenian".
}


def kaikki_language_name(language: Language) -> str:
    """Name of a language on kaikki.org, used in its words-file URL and cache.

    kaikki.org names most languages as Emmio's `get_name()` does, but a few
    differ; this is the single source of truth for the Kaikki name so the
    download URL, the on-disk cache, and `has_kaikki` all agree.
    """
    return _KAIKKI_NAME_OVERRIDES.get(language.get_code(), language.get_name())


PART_OF_SPEECH_MAP: dict[str, str] = {
    "prep": "preposition",
    "adv": "adverb",
    "adj": "adjective",
    "num": "numeral",
    "intj": "interjection",
    "det": "determiner",
    "conj": "conjunction",
    "pron": "pronoun",
}


class DictionaryDownloadError(Exception):
    """Downloading dictionary data from a remote service failed."""


class EnglishWiktionaryKaikki(Dictionary):
    """English Wiktionary parsed by wikiextract.

    Results of parsing English Wiktionary by wikiextract are available at
    Kaikki website.

    See https://kaikki.org, https://github.com/tatuylonen/wikiextract.
    """

    def __init__(
        self,
        path: Path,
        cache_directory: Path,
        from_language: Language,
        from_language_name: str,
    ) -> None:
        """Initialize dictionary.

        :param cache_directory: directory used to store cache files
        :param from_language: source language specification
        :param from_language_name: name of language on `kaikki.org` website
        """

        if not from_language.has_symbols():
            msg: str = (
                f"Language `{from_language.get_name()}` does not have symbols."
            )
            raise ValueError(msg)

        super().__init__("kaikki")
        self.path: Path = path
        self.from_language: Language = from_language
        self.from_language_name: str = from_language_name
        self.items: dict[str, DictionaryItem] = {}

        self.processed_file_paths: set[Path] = set()
        self.cache_directory: Path = (
            cache_directory / "kaikki" / self.from_language_name
        )
        if self.cache_directory.exists():
            return

        file_path: Path = (
            self.path
            / f"kaikki.org-dictionary-{self.from_language_name}-words.jsonl"
        )
        if not file_path.exists():
            logger.info("File `%s` does not exist.", file_path)
            self.download_words(file_path)
        self.create_cache(file_path)

        # Remove `.jsonl` file.
        file_path.unlink()

    def download_words(self, file_path: Path) -> None:
        """Download the JSONL words file from the Kaikki website.

        The file is streamed to a `.part` file and renamed only once the
        download completes, so an interrupted download is never mistaken for
        the real file.

        :param file_path: where to put the downloaded file
        :raises DictionaryDownloadError: if the download fails for any reason
        """
        logger.info("Downloading `%s` Kaikki...", self.from_language_name)
        url: str = (
            f"https://kaikki.org/dictionary/{self.from_language_name}/"
            f"words/kaikki.org-dictionary-"
            f"{self.from_language_name.replace(' ', '')}-words.jsonl"
        )
        part_path: Path = file_path.with_name(file_path.name + ".part")
        try:
            response: requests.Response = requests.get(
                url, stream=True, timeout=60
            )
            response.raise_for_status()
            with part_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        output_file.write(chunk)
        except (requests.RequestException, OSError) as error:
            part_path.unlink(missing_ok=True)
            msg: str = (
                f"Failed to download `{self.from_language_name}` Kaikki "
                f"from `{url}`."
            )
            raise DictionaryDownloadError(msg) from error
        part_path.rename(file_path)

    def create_cache(self, file_path: Path) -> None:
        """Split the words file into per-prefix cache files.

        Cache files are written to a `.part` directory that is renamed to the
        cache directory only after every word is processed, so a failed or
        interrupted run does not leave behind a directory that looks like a
        valid (but empty or partial) cache.

        :param file_path: the downloaded JSONL words file
        """
        logger.info(
            "Creating cache for `%s` Kaikki...", self.from_language.get_name()
        )
        part_directory: Path = self.cache_directory.with_name(
            self.cache_directory.name + ".part"
        )
        if part_directory.exists():
            shutil.rmtree(part_directory)
        part_directory.mkdir(parents=True)

        try:
            with file_path.open(encoding="utf-8") as input_file:
                for line in tqdm(input_file):
                    item = json.loads(line)
                    word: str = item["word"]
                    if len(word) >= 1:
                        if not self.from_language.is_word(word):
                            continue
                        cache_file_path: Path = self.get_cache_file_path(
                            word, part_directory
                        )
                        cache_file_path.parent.mkdir(
                            parents=True, exist_ok=True
                        )
                        with cache_file_path.open(
                            "a", encoding="utf-8"
                        ) as output_file:
                            output_file.write(line)
        except BaseException:
            shutil.rmtree(part_directory, ignore_errors=True)
            raise

        part_directory.rename(self.cache_directory)

    def __repr__(self) -> str:
        return f"English Wiktionary Kaikki [{len(self.items)}]"

    @override
    def get_name(self) -> str:
        return "English Wiktionary Kaikki"

    def get_cache_file_path(
        self, word: str, directory: Path | None = None
    ) -> Path:
        """Get path to cache file for a word.

        :param word: word to get cache file path for
        :param directory: base directory (default: the cache directory)
        :return: path to cache file
        """
        if directory is None:
            directory = self.cache_directory
        return directory / word[0].lower() / f"{word[:2].lower()}.jsonl"

    def process_item(
        self, item: dict[str, Any], dictionary_item: DictionaryItem
    ) -> None:
        """Process item from Kaikki.

        :param item: item from Kaikki JSONL file
        :param dictionary_item: dictionary item to add forms to
        """

        word: str = item["word"]

        transcriptions: set[str] = (
            {x["ipa"] for x in item["sounds"] if "ipa" in x}
            if "sounds" in item
            else set()
        )

        # TODO(enzet): etymology is replaced. We should parse only one
        # dictionary item for an item.
        dictionary_item.set_etymology(item.get("etymology_text"))

        definitions: list[Definition] = []
        links: list[Link] = []

        for sense in item["senses"]:
            tags: list[str]

            if "form_of" in sense:
                tags = sense["tags"]
                links.extend(
                    Link(
                        ", ".join(x for x in tags if x != "form-of"),
                        form["word"],
                    )
                    for form in sense["form_of"]
                )
                continue

            if "alt_of" in sense:
                tags = sense["tags"]
                links.extend(
                    Link(
                        ", ".join(x for x in tags if x != "alt-of"),
                        form["word"],
                    )
                    for form in sense["alt_of"]
                )
                continue

            # TODO(enzet): dirty hacks.
            if "categories" in sense:
                for category in sense["categories"]:
                    if (
                        "parents" in category
                        and "Letter names" in category["parents"]
                    ):
                        continue

            definition_values: list[DefinitionValue] = []
            if "glosses" in sense:
                definition_values.extend(
                    DefinitionValue.from_text(gloss)
                    for gloss in sense["glosses"]
                )

            descriptors: list[str] = sense.get("tags", [])

            definitions.append(
                Definition(definition_values, descriptors=descriptors)
            )

        part_of_speech: str = item["pos"]
        part_of_speech = PART_OF_SPEECH_MAP.get(part_of_speech, part_of_speech)

        dictionary_item.add_form(
            Form(
                word=word,
                part_of_speech=part_of_speech,
                transcriptions=transcriptions,
                definitions={KnownLanguages.ENGLISH: definitions},
                links=links,
            )
        )

    @override
    async def get_item(
        self, word: str, *, cache_only: bool = False
    ) -> DictionaryItem | None:
        # Return already loaded item.
        if word in self.items:
            return self.items[word]

        # If cache file does not exist, return `None`.
        if not (cache_file_path := self.get_cache_file_path(word)).exists():
            return None

        # Parse all items from cache file.
        if cache_file_path in self.processed_file_paths:
            return None
        self.processed_file_paths.add(cache_file_path)

        dictionary_item: DictionaryItem
        with cache_file_path.open(encoding="utf-8") as input_file:
            for line in input_file.readlines():
                item: dict[str, Any] = json.loads(line)
                if item["word"] in self.items:
                    dictionary_item = self.items[item["word"]]
                else:
                    dictionary_item = DictionaryItem(item["word"])
                    self.items[item["word"]] = dictionary_item
                self.process_item(
                    item, dictionary_item
                )  # Fill dictionary item.

        return self.items.get(word)

    @override
    def check_from_language(self, language: Language) -> bool:
        return language == self.from_language

    @override
    def check_to_language(self, language: Language) -> bool:
        return language == KnownLanguages.ENGLISH
