"""
Gate for English Wiktionary service.

See https://en.wiktionary.org.

Author: Sergey Vartanov (me@enzet.ru).
"""
import json
import os
import re
from pathlib import Path
from typing import Optional

from wiktionaryparser import WiktionaryParser

from emmio.dictionary import Dictionary, DictionaryItem, Form, Link
from emmio.language import Language
from emmio.ui import network, error


FORMS: set[str] = {
    "accusative",
    "affirmative",
    "adverb",
    "comparative",
    "conditional",
    "dative",
    "degree",
    "feminine",
    "first",
    "first-person",
    "formal",
    "future",
    "genitive",
    "gerund",
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
    "participle",
    "past",
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

    def process_definition(self, text: str) -> tuple[list[Link], str]:
        text = text.strip()

        matcher: Optional[re.Match] = re.match(
            "^(?P<link_type>.*) form of (?P<link>[^:;,. ]*)"
            "(\\s*\\(.*\\))?[.:]?$",
            text,
        )
        if matcher:
            link: str = matcher.group("link")
            link_type: str = matcher.group("link_type")
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

    def get_item(self, word: str) -> Optional[DictionaryItem]:
        """
        Parse dictionary item from English Wiktionary.

        :param word: dictionary term
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
            network(f"getting English Wiktionary item")
            try:
                content: Optional[
                    dict[str, dict[str, any]]
                ] = self.parser.fetch(word, self.from_language.get_name())
                with open(path, "w+") as output_file:
                    json.dump(content, output_file)
            except (KeyError, AttributeError):
                error("malformed HTML")
                content = None

        if not content:
            return None

        item: DictionaryItem = DictionaryItem(word)
        added: bool = False

        for element in content:
            for definition in element["definitions"]:
                form: Form = Form(word, definition["partOfSpeech"])
                texts: list[str] = definition["text"]

                for text in texts:
                    links, text = self.process_definition(text)
                    if links:
                        for link in links:
                            form.add_link(link)
                    else:
                        # FIXME: should be "en"
                        form.add_translation(text, "ru")

                if "pronunciations" in element:
                    for pronunciation in element["pronunciations"]["text"]:
                        form.add_transcription(pronunciation.strip())
                item.add_definition(form)
                added = True

        if added:
            return item

    def get(
        self,
        word: str,
        language: str,
        show_word: bool = True,
        hide_translations: list[str] = None,
        use_colors: bool = False,
    ) -> Optional[str]:

        item: Optional[DictionaryItem] = self.get_item(word)
        if item:
            return item.to_str(
                language, show_word, use_colors, hide_translations
            )
