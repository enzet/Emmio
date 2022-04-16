"""
Gate for English Wiktionary service.

See https://en.wiktionary.org.

Author: Sergey Vartanov (me@enzet.ru).
"""
import json
import os
import re
from typing import Any, Dict, List, Optional

from wiktionaryparser import WiktionaryParser

from emmio.dictionary import Dictionary, DictionaryItem, Form
from emmio.language import Language
from emmio.ui import network, error


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

    def __init__(self, cache_directory: str, from_language: Language):
        """
        Target language.

        :param cache_directory: directory for cache files
        :param from_language: target language
        """
        super().__init__()
        self.from_language: Language = from_language
        self.cache_directory: str = cache_directory
        self.parser: WiktionaryParser = WiktionaryParser()

    def get_item(self, word: str) -> Optional[DictionaryItem]:
        """
        Parse dictionary item from English Wiktionary.

        :param word: dictionary term
        :returns: parsed item
        """
        path: str = os.path.join(
            self.cache_directory, "en_wiktionary", self.from_language.get_code()
        )
        os.makedirs(path, exist_ok=True)
        path: str = os.path.join(path, f"{word}.json")

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
                texts: List[str] = definition["text"]
                for text in texts:
                    text = text.strip()
                    matcher: Optional[re.Match] = re.match(
                        "^(?P<link_type>.*) of (?P<link>[^:;,. ]*)[.:]?$", text
                    )
                    if matcher:
                        link: str = matcher.group("link")
                        link = self.from_language.decode_text(link)
                        form.add_link(matcher.group("link_type"), link)
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
        hide_translations: List[str] = None,
        use_colors: bool = False,
    ) -> Optional[str]:

        item: Optional[DictionaryItem] = self.get_item(word)
        if item:
            return item.to_str(
                language, show_word, use_colors, hide_translations
            )

    def get_name(self) -> str:
        """Return dictionary name."""
        return "English Wiktionary"
