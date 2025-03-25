"""Gate for English Wiktionary service.

See https://en.wiktionary.org.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, override

import requests
from tqdm import tqdm

from emmio.dictionary import CONFIG
from emmio.dictionary.core import (
    Definition,
    DefinitionValue,
    Dictionary,
    DictionaryItem,
    Form,
    Link,
)
from emmio.language import ENGLISH, Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

PRONUNCIATION_PREFIXES: set[str] = set(CONFIG["pronunciation_prefixes"])
FORMS: set[str] = set(CONFIG["forms"])
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


LINK_PATTERN: re.Pattern[str] = re.compile(
    r"^(?P<preffix>\(.*\) )?(?P<link_type>.*) of "
    r"(?P<link>[^:;,. ]*)[:;,.]?"
    r'(?P<suffix1>[:;,] .*)?(?P<suffix2> \(.*\))?(?P<suffix3> ".*")?$'
)
DESCRIPTOR_PATTERN: re.Pattern[str] = re.compile(
    r"\((?P<descriptor>[^()]*)\) .*"
)


def get_file_name(word: str) -> str:
    """Get file name for cache JSON file.

    For this to work on case-insensitive operating systems, we add special
    symbol `^` before the capitalized letter.
    """
    name: str = "".join(f"^{c.lower()}" if c.lower() != c else c for c in word)

    return f"{name}.json"


def check_link_type(link_type: str) -> bool:
    """Check if the link type is valid.

    TODO: recheck this function and probably remove.

    :param link_type: link type
    :return: true iff the link type is valid
    """
    link_type = (
        link_type.replace("(t\u00fa)", "")
        .replace("(usted)", "")
        .replace("(ustedes)", "")
        .replace("(yo)", "")
        .replace("(nosotros, nosotras)", "")
        .replace("(\u00e9l, ella, also used with usted?)", "")
        .replace("(ellos; ellas; also used with ustedes?)", "")
        .replace("/", " ")
        .replace("(", "")
        .replace(")", "")
        .replace(" and ", " ")
        .replace("  ", " ")
        .lower()
    )
    return all(not x or x in FORMS for x in link_type.split(" "))


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
        """
        :param cache_directory: directory used to store cache files
        :param from_language: source language specification
        :param from_language_name: name of language on `kaikki.org` website
        """

        if not from_language.has_symbols():
            logging.error(
                "Language `%s` does not have symbols.", from_language.get_name()
            )
            sys.exit(1)

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

        os.makedirs(self.cache_directory)
        file_path: Path = (
            self.path
            / f"kaikki.org-dictionary-{self.from_language_name}-words.jsonl"
        )
        if not file_path.exists():
            logging.info("File `%s` does not exist.", file_path)
            logging.info("Downloading `%s` Kaikki...", self.from_language_name)
            url: str = (
                f"https://kaikki.org/dictionary/{self.from_language_name}/"
                f"words/kaikki.org-dictionary-"
                f'{self.from_language_name.replace(" ", "")}-words.jsonl'
            )
            response: requests.Response = requests.get(
                url, stream=True, timeout=5
            )
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError:
                logging.error(
                    "Failed to download `%s` Kaikki from `%s`.",
                    self.from_language_name,
                    url,
                )
                # Remove created directory.
                os.rmdir(self.cache_directory)
                sys.exit(1)
            with file_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        output_file.write(chunk)

        logging.info(
            "Creating cache for `%s` Kaikki...", self.from_language.get_name()
        )
        with file_path.open(encoding="utf-8") as input_file:
            for line in tqdm(input_file.readlines()):
                item = json.loads(line)
                word: str = item["word"]
                if len(word) >= 1:
                    if not all(self.from_language.has_symbol(c) for c in word):
                        continue
                    (self.cache_directory / word[0].lower()).mkdir(
                        parents=True, exist_ok=True
                    )
                    with self.get_cache_file_path(word).open(
                        "a", encoding="utf-8"
                    ) as output_file:
                        output_file.write(line)

        # Remove `.jsonl` file.
        file_path.unlink()

    def __repr__(self) -> str:
        return f"English Wiktionary Kaikki [{len(self.items)}]"

    @override
    def get_name(self) -> str:
        return "English Wiktionary Kaikki"

    def get_cache_file_path(self, word: str) -> Path:
        """Get path to cache file for a word.

        :param word: word to get cache file path for
        :return: path to cache file
        """
        return (
            self.cache_directory / word[0].lower() / f"{word[:2].lower()}.jsonl"
        )

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

        # FIXME: etymology is replaced. We should parse only one dictionary item
        #     for an item.
        dictionary_item.set_etymology(item.get("etymology_text"))

        definitions: list[Definition] = []
        links: list[Link] = []

        for sense in item["senses"]:

            tags: list[str]

            if "form_of" in sense:
                tags = sense["tags"]
                for form in sense["form_of"]:
                    links.append(
                        Link(
                            ", ".join(x for x in tags if x != "form-of"),
                            form["word"],
                        )
                    )
                continue

            if "alt_of" in sense:
                tags = sense["tags"]
                for form in sense["alt_of"]:
                    links.append(
                        Link(
                            ", ".join(x for x in tags if x != "alt-of"),
                            form["word"],
                        )
                    )
                continue

            # FIXME: dirty hacks:
            if "categories" in sense:
                for category in sense["categories"]:
                    if (
                        "parents" in category
                        and "Letter names" in category["parents"]
                    ):
                        continue

            definition_values: list[DefinitionValue] = []
            if "glosses" in sense:
                for gloss in sense["glosses"]:
                    definition_values.append(DefinitionValue.from_text(gloss))

            descriptors: list[str] = sense["tags"] if "tags" in sense else []

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
                definitions={ENGLISH: definitions},
                links=links,
            )
        )

    @override
    async def get_item(
        self, word: str, cache_only: bool = False
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
        return language == ENGLISH

    @override
    def check_is_machine(self) -> bool:
        return False
