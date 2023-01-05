"""
Gate for English Wiktionary service.

See https://en.wiktionary.org.
"""
import json
import logging
import os
import re
import requests
from pathlib import Path
from time import sleep
from typing import Any

from wiktionaryparser import WiktionaryParser

from emmio.dictionary import CONFIG
from emmio.dictionary.core import (
    Definition,
    DefinitionValue,
    Dictionary,
    DictionaryItem,
    Form,
    Link,
)
from emmio.language import Language, ENGLISH

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

PRONUNCIATION_PREFIXES: set[str] = set(CONFIG["pronunciation_prefixes"])
FORMS: set[str] = set(CONFIG["forms"])


LINK_PATTERN: re.Pattern = re.compile(
    r"^(?P<preffix>\(.*\) )?(?P<link_type>.*) of "
    r"(?P<link>[^:;,. ]*)[:;,.]?"
    r'(?P<suffix1>[:;,] .*)?(?P<suffix2> \(.*\))?(?P<suffix3> ".*")?$'
)
DESCRIPTOR_PATTERN: re.Pattern = re.compile(r"\((?P<descriptor>[^()]*)\) .*")


def get_file_name(word: str):
    """
    Get file name for cache JSON file.

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


class EnglishWiktionary(Dictionary):
    """
    Dictionary that uses English Wiktionary API.

    See https://en.wiktionary.org.
    """

    def __init__(self, cache_directory: Path, from_language: Language):
        """
        :param cache_directory: directory for cache files
        :param from_language: target language
        """
        super().__init__()
        self.from_language: Language = from_language
        self.cache_directory: Path = cache_directory
        self.parser: WiktionaryParser = WiktionaryParser()

    @staticmethod
    def process_definition(text: str) -> Link | Definition:

        # Preparsing.
        text = text.strip()
        if text.endswith("."):
            text = text[:-1]

        if matcher := LINK_PATTERN.match(text):
            link_type: str = matcher.group("link_type")
            if check_link_type(link_type):
                return Link(link_type, matcher.group("link"))

        descriptors: list[str] = []

        if matcher := DESCRIPTOR_PATTERN.match(text):
            p = matcher.group("descriptor")
            descriptors = p.split(", ")
            text = text[len(p) + 3 :]

        values: list[DefinitionValue]
        if "; " in text:
            values = [DefinitionValue.from_text(x) for x in text.split("; ")]
        elif ", " in text:
            values = [DefinitionValue.from_text(x) for x in text.split(", ")]
        else:
            values = [DefinitionValue.from_text(text)]

        return Definition(values, descriptors)

    def parse_form(
        self, word: str, definition: dict[str, Any], pronunciations: list[str]
    ) -> Form | None:

        form: Form = Form(word, definition["partOfSpeech"])

        if "text" not in definition or not definition["text"]:
            return None

        first_definition: str = definition["text"][0]
        if re.split("[  ]", first_definition)[0] == word:
            definitions = definition["text"][1:]
        else:
            definitions = definition["text"]

        first_word: str = first_definition.split(" ")[0]
        if first_word == f"{word} f":
            form.gender = "f"
        elif first_word == f"{word} m":
            form.gender = "m"

        for text in definitions:
            element = self.process_definition(text)
            if isinstance(element, Link):
                form.add_link(element)
            elif isinstance(element, Definition):
                form.add_translation(element, ENGLISH)

        for pronunciation in pronunciations:
            form.add_transcription(pronunciation)

        return form

    def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:
        """
        Parse dictionary item from English Wiktionary.

        :param word: dictionary term
        :param cache_only: return dictionary term only if it is in cache
        :returns: parsed item
        """
        directory: Path = (
            self.cache_directory
            / "en_wiktionary"
            / self.from_language.get_code()
        )
        os.makedirs(directory, exist_ok=True)

        path: Path = directory / get_file_name(word)

        if os.path.isfile(path):
            with open(path) as input_file:
                content = json.load(input_file)
        else:
            if cache_only:
                return None

            logging.info("Sleeping for 1 second...")
            sleep(1)
            logging.info("Getting English Wiktionary item...")
            try:
                content: list[dict[str, Any]] | None = self.parser.fetch(
                    word, self.from_language.get_name()
                )
                with open(path, "w+") as output_file:
                    json.dump(content, output_file)
            except requests.exceptions.ConnectionError:
                logging.error("Connection error.")
                return None
            except (KeyError, AttributeError):
                logging.error("Malformed HTML.")
                return None

        if not content:
            return None

        item: DictionaryItem = DictionaryItem(word)

        for element in content:

            pronunciations: list[str] = []

            if "pronunciations" in element:
                for pronunciation in element["pronunciations"]["text"]:
                    pronunciation = pronunciation.strip()
                    if pronunciation.startswith("IPA: "):
                        pronunciation = pronunciation[5:]

                    found_prefix: bool = False

                    for prefix in PRONUNCIATION_PREFIXES:
                        if pronunciation.startswith(
                            prefix[0].upper() + prefix[1:] + ": "
                        ):
                            found_prefix = True
                            break

                    if found_prefix:
                        continue

                    pronunciations.append(pronunciation.strip())

            for definition in element["definitions"]:
                form: Form | None = self.parse_form(
                    word, definition, pronunciations
                )
                if form is not None:
                    item.add_definition(form)

        if item.has_definitions():
            return item

    def check_from_language(self, language: Language) -> bool:
        return self.from_language == language

    def check_to_language(self, language: Language) -> bool:
        return language == ENGLISH
