"""
Gate for English Wiktionary service.

See https://en.wiktionary.org.

Author: Sergey Vartanov (me@enzet.ru).
"""
import json
import os
import re
from pathlib import Path
from time import sleep
from typing import Optional, Any, Union

from wiktionaryparser import WiktionaryParser

from emmio.dictionary import (
    Dictionary,
    DictionaryItem,
    Form,
    Link,
    Definition,
    DefinitionValue,
)
from emmio.language import Language
from emmio.ui import network, error


FORMS: set[str] = {
    "accusative",
    "active",
    "affirmative",
    "adverb",
    "adverbial",
    "comparative",
    "conditional",
    "dative",
    "degree",
    "dependent",
    "feminine",
    "first",
    "first-person",
    "formal",
    "future",
    "genitive",
    "gerund",
    "historic",
    "imperative",
    "imperfect",
    "indicative",
    "indefinite",
    "inflection",
    "informal",
    "masculine",
    "mixed",
    "neuter",
    "nominative",
    "nominal",
    "participle",
    "past",
    "passive",
    "plural",
    "present",
    "preterite",
    "pronominal",
    "second-person",
    "simple",
    "singular",
    "strong",
    "subjunctive",
    "superlative",
    "tense",
    "third-person",
    "i",
    "ii",
    "iii",
    "of",
    "the",
}


LINK_PATTERN: re.Pattern = re.compile(
    "^(?P<preffix>\\(.*\\) )?(?P<link_type>.*) of (?P<link>[^:;,. ]*)[.:]?"
    '(?P<suffix1>[,;] .*)?(?P<suffix2> \\(.*\\))?(?P<suffix3> ".*")?$'
)


def get_file_name(word: str):
    """
    Get file name for cache JSON file for case-insensitive operating systems.
    """
    name: str = "".join(f"^{c.lower()}" if c.lower() != c else c for c in word)

    return f"{name}.json"


class EnglishWiktionary(Dictionary):
    """
    Dictionary that uses English Wiktionary API.

    See https://en.wiktionary.org.
    """

    def __init__(self, cache_directory: Path, from_language: Language):
        """
        Target language.

        :param cache_directory: directory for cache files
        :param from_language: target language
        """
        super().__init__()
        self.from_language: Language = from_language
        self.cache_directory: Path = cache_directory
        self.parser: WiktionaryParser = WiktionaryParser()

        self.add_obsolete: bool = False

    @staticmethod
    def process_definition(text: str) -> tuple[list[Link], str]:
        text = text.strip()

        matcher: Optional[re.Match] = re.match(
            "^(?P<link_type>.*) form of (?P<link>[^:;,. ]*)"
            "(\\s*\\(.*\\))?[.:]?$",
            text,
        )
        if matcher:
            link: str = matcher.group("link")
            link_type: str = matcher.group("link_type")

            if link_type.lower() == "obsolete":
                return [], ""

            return [Link(link_type, link)], text

        matcher: Optional[re.Match] = LINK_PATTERN.match(text)
        if matcher:
            link: str = matcher.group("link")
            link_type: str = (
                matcher.group("link_type")
                .replace("/", " ")
                .replace(" and ", " ")
                .lower()
            )
            if all(not x or x in FORMS for x in link_type.split(" ")):
                return [Link(link_type, link)], text

        return [], text

    def parse_form(
        self,
        word: str,
        definition: dict[str, Any],
        pronunciations: list[str],
    ) -> Form:

        form: Form = Form(word, definition["partOfSpeech"])

        for text in definition["text"]:
            links, text = self.process_definition(text)
            if links:
                for link in links:
                    form.add_link(link)
            elif text:
                # FIXME: should be "en"
                form.add_translation(text, "ru")

        for pronunciation in pronunciations:
            form.add_transcription(pronunciation)

        return form

    def get_item(
        self, word: str, cache_only: bool = False
    ) -> Optional[DictionaryItem]:
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

            network(f"getting English Wiktionary item")
            sleep(1)
            try:
                content: Optional[list[dict[str, Any]]] = self.parser.fetch(
                    word, self.from_language.get_name()
                )
                with open(path, "w+") as output_file:
                    json.dump(content, output_file)
            except (KeyError, AttributeError):
                error("malformed HTML")
                content = None

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
                    if (
                        pronunciation.startswith("Rhymes: ")
                        or pronunciation.startswith("Syllabification: ")
                        or pronunciation.startswith("Hyphenation: ")
                        or pronunciation.startswith("Homophone: ")
                        or pronunciation.startswith("Homophones: ")
                    ):
                        continue
                    pronunciations.append(pronunciation.strip())

            for definition in element["definitions"]:
                item.add_definition(
                    self.parse_form(word, definition, pronunciations)
                )

        if item.has_definitions():
            return item
