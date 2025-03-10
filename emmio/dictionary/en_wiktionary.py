"""Gate for English Wiktionary service.

See https://en.wiktionary.org.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

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


LINK_PATTERN: re.Pattern = re.compile(
    r"^(?P<preffix>\(.*\) )?(?P<link_type>.*) of "
    r"(?P<link>[^:;,. ]*)[:;,.]?"
    r'(?P<suffix1>[:;,] .*)?(?P<suffix2> \(.*\))?(?P<suffix3> ".*")?$'
)
DESCRIPTOR_PATTERN: re.Pattern = re.compile(r"\((?P<descriptor>[^()]*)\) .*")


def get_file_name(word: str):
    """Get file name for cache JSON file.

    For this to work on case-insensitive operating systems, we add special
    symbol ``^`` before the capitalized letter.
    """
    name: str = "".join(f"^{c.lower()}" if c.lower() != c else c for c in word)

    return f"{name}.json"


def check_link_type(link_type: str) -> bool:
    link_type: str = (
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
                f"Language {from_language.get_name()} does not have symbols."
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
            logging.info(f"File {file_path} does not exist.")
            logging.info(f"Downloading {self.from_language_name} Kaikki...")
            url: str = (
                f"https://kaikki.org/dictionary/{self.from_language_name}/"
                f'words/kaikki.org-dictionary-{self.from_language_name.replace(" ", "")}-words.jsonl'
            )
            response: requests.Response = requests.get(url, stream=True)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError:
                logging.error(
                    f"Failed to download {self.from_language_name} Kaikki from `{url}`."
                )
                # Remove created directory.
                os.rmdir(self.cache_directory)
                sys.exit(1)
            with file_path.open("wb") as output_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        output_file.write(chunk)

        logging.info(
            f"Creating cache for {self.from_language.get_name()} Kaikki..."
        )
        with open(file_path) as input_file:
            for line in tqdm(input_file.readlines()):
                item = json.loads(line)
                word: str = item["word"]
                if len(word) >= 1:
                    if not all(self.from_language.has_symbol(c) for c in word):
                        continue
                    (self.cache_directory / word[0].lower()).mkdir(
                        parents=True, exist_ok=True
                    )
                    with open(
                        self.get_cache_file_path(word), "a"
                    ) as output_file:
                        output_file.write(line)

        # Remove `.jsonl` file.
        file_path.unlink()

    def __repr__(self) -> str:
        return f"English Wiktionary Kaikki [{len(self.items)}]"

    def get_name(self) -> str:
        return "English Wiktionary Kaikki"

    def get_cache_file_path(self, word: str) -> Path:
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

        transcriptions: list[str] = (
            [x["ipa"] for x in item["sounds"] if "ipa" in x]
            if "sounds" in item
            else []
        )

        # FIXME: etymology is replaced. We should parse only one dictionary item
        #        for an item.
        dictionary_item.set_etymology(item.get("etymology_text"))

        definitions: list[Definition] = []
        links: list[Link] = []

        # print(f"len(item['senses']): {len(item['senses'])}")

        for sense in item["senses"]:

            if "form_of" in sense:
                tags: list[str] = sense["tags"]
                # print(f"len(sense['form_of']): {len(sense['form_of'])}")
                for form in sense["form_of"]:
                    links.append(
                        Link(
                            ", ".join(x for x in tags if x != "form-of"),
                            form["word"],
                        )
                    )
                continue

            if "alt_of" in sense:
                tags: list[str] = sense["tags"]
                # print(f"len(sense['alt_of']): {len(sense['alt_of'])}")
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
                # print(f"len(sense['glosses']): {len(sense['glosses'])}")
                for gloss in sense["glosses"]:
                    definition_values.append(DefinitionValue.from_text(gloss))

            descriptors: list[str] = sense["tags"] if "tags" in sense else []

            definitions.append(
                Definition(definition_values, descriptors=descriptors)
            )

        part_of_speech: str = item["pos"]
        part_of_speech = PART_OF_SPEECH_MAP.get(part_of_speech, part_of_speech)

        form: Form = Form(
            word=word,
            part_of_speech=part_of_speech,
            transcriptions=transcriptions,
            definitions={ENGLISH: definitions},
            links=links,
        )
        dictionary_item.add_form(form)

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
        with open(cache_file_path) as input_file:
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
