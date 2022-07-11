"""
Dictionary.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from emmio.language import Language
from emmio.ui import Interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


DESCRIPTORS_OF_WORDS_TO_IGNORE: list[str] = [
    "archaic",
    # "colloquial",
    "dated",
    "figuratively",
    # "informal",
    "obsolete",
    "rare",
    "slang",
    "spelling",
]


@dataclass
class Link:
    link_type: str
    link_value: str

    def is_common(self) -> bool:
        """
        Check whether this link is common.

        Meaning is not
            - slang, colloquial,
            - obsolete, etc.
        """
        parts = self.link_type.lower().split(" ")

        for descriptor in DESCRIPTORS_OF_WORDS_TO_IGNORE:
            if descriptor in parts:
                return False

        return True

    def __hash__(self):
        return hash(f"{self.link_type}_{self.link_value}")


def hide(text: str, words_to_hide: list[str]) -> str:
    for word in words_to_hide:
        if "́" in text:
            if word in text.replace("́", ""):
                start: int = text.replace("́", "").find(word)
                text = (
                    text[:start]
                    + "_" * len(word)
                    + text[start + len(word) + 1 :]
                )

        text = text.replace(word, "_" * len(word))

        while word.lower() in text.lower():
            start: int = text.lower().find(word.lower())
            text = text[:start] + "_" * len(word) + text[start + len(word) :]

    return text


@dataclass
class DefinitionValue:

    value: str
    description: str = ""

    @classmethod
    def from_text(cls, text: str) -> "DefinitionValue":
        if matcher := re.match(
            "(?P<value>[^(]*) \\((?P<description>.*)\\)$", text
        ):
            return cls(matcher.group("value"), matcher.group("description"))

        return cls(text)

    def to_str(self, to_hide: Optional[list[str]] = None) -> Optional[str]:
        """Get human-readable form of definition."""

        value: str = self.value

        if to_hide is not None:
            value = hide(value, to_hide)

        return value + (
            f" ({self.description})"
            if self.description and to_hide is None
            else ""
        )


@dataclass
class Definition:

    values: list[DefinitionValue]
    descriptors: list[str] = field(default_factory=list)

    def is_common(self) -> bool:
        """
        Check whether this definition is common.

        Meaning is not
            - slang, colloquial,
            - obsolete, etc.
        """
        for description in DESCRIPTORS_OF_WORDS_TO_IGNORE:
            if description in self.descriptors:
                return False
        return True

    def to_str(self, to_hide: Optional[list[str]] = None) -> Optional[str]:
        """Get human-readable form of definition."""
        if to_hide is not None and not self.is_common():
            return None

        result: str = ""

        if self.descriptors and to_hide is None:
            result += "(" + ", ".join(self.descriptors) + ") "

        result += "; ".join(x.to_str(to_hide) for x in self.values)

        return result


@dataclass
class Form:
    """Word form: noun, verb, etc."""

    word: str

    part_of_speech: str
    transcriptions: set[str] = field(default_factory=set)
    translations: dict[Language, list[Definition]] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)

    # Optional characteristics.
    gender: Optional[str] = None
    verb_group: Optional[int] = None
    is_singular: Optional[bool] = None

    def add_transcription(self, transcription: str) -> None:
        """Add word form IPA transcription."""
        self.transcriptions.add(transcription)

    def add_translations(
        self, translations: list[Definition], language: Language
    ) -> None:
        """Add word translations."""
        for translation in translations:
            self.add_translation(translation, language)

    def add_translation(
        self, translation: Definition, language: Language
    ) -> None:
        """
        Add word translation.  It is assumed that translations are sorted by
        usage frequency.

        :param language: language of translation
        :param translation: word translation
        """
        if language not in self.translations:
            self.translations[language] = []
        self.translations[language].append(translation)

    def add_link(self, link: Link) -> None:
        """
        Add link to another dictionary item if the word is a form of other word.

        :param link: link to another dictionary item
        """
        self.links.append(link)

    def has_common_definition(self, language: Language) -> bool:
        """
        Check whether the form has at least one common definition.

        Also check if it is not just a form of some another word.
        """
        if self.part_of_speech == "letter":
            return False

        if language in self.translations:
            for definition in self.translations[language]:
                if definition.is_common():
                    return True

        return False

    def to_str(
        self,
        language: Language,
        interface: Interface,
        show_word: bool = True,
        words_to_hide: set[str] = None,
        hide_translations: set[str] = None,
        only_common: bool = True,
    ) -> str:
        """Get human-readable representation of the word form."""
        to_hide: Optional[list[str]] = None

        if not show_word:
            to_hide = sorted(
                list(words_to_hide | hide_translations), key=lambda x: -len(x)
            )

        desc = self.part_of_speech
        if show_word and self.transcriptions:
            if self.gender is not None:
                desc += f" {self.gender}"
            desc += " " + ", ".join(map(lambda x: f"{x}", self.transcriptions))

        definitions: list[str] = []

        if self.translations and language in self.translations:
            for translation in self.translations[language]:
                string: Optional[str] = translation.to_str(to_hide)
                if string is not None and string not in definitions:
                    definitions.append(string)

        links: list[Link] = self.get_links(only_common)

        if not definitions and not links:
            return ""

        result: str = interface.colorize(desc, "grey") + "\n"

        if definitions:
            result += "    " + "\n    ".join(definitions) + "\n"

        for link in links:
            if show_word:
                result += f"    -> {link.link_type} of {link.link_value}\n"
            else:
                result += f"    -> {link.link_type}\n"

        return result

    def get_links(self, only_common: bool = True):
        return [
            link for link in self.links if not only_common or link.is_common()
        ]


class DictionaryItem:
    """Dictionary item: word translations."""

    def __init__(self, word: str):
        self.word: str = word
        self.definitions: list[Form] = []

    def add_definition(self, form: Form):
        """Add word form to dictionary item."""
        self.definitions.append(form)

    def get_links(self) -> set[Link]:
        """
        Get keys to other dictionary items this dictionary item is linked to.
        """
        return set(
            [
                link
                for definition in self.definitions
                for link in definition.get_links()
            ]
        )

    def to_str(
        self,
        language: Language,
        interface: Interface,
        show_word: bool = True,
        words_to_hide: Optional[set[str]] = None,
        hide_translations: Optional[set[str]] = None,
    ) -> str:
        """
        Get human-readable representation of the dictionary item.

        :param language: the language of translation
        :param interface: user interface provider
        :param show_word: if false, hide word transcription and word occurrences
            in examples
        :param words_to_hide: set of words to be hidden from the output
        :param hide_translations: list of translations that should be hidden
        """
        result: str = ""

        if show_word:
            result += self.word + "\n"

        for definition in self.definitions:
            result += definition.to_str(
                language, interface, show_word, words_to_hide, hide_translations
            )

        return result

    def has_definitions(self) -> bool:
        """Check whether the dictionary item has at least one definition."""
        return len(self.definitions) > 0

    def has_common_definition(self, language: Language) -> bool:
        """
        Check whether the form has at least one common definition.

        Also check if it is not just a form of some another word.
        """
        for definition in self.definitions:
            if definition.has_common_definition(language):
                return True

        return False


class Dictionary:
    """Dictionary of word definitions."""

    def __init__(self) -> None:
        self.__items: dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        """Add word definition."""
        self.__items[word] = item

    def get_item(
        self, word: str, cache_only: bool = False
    ) -> Optional[DictionaryItem]:
        """Get word definition."""

        if word in self.__items:
            return self.__items[word]

        return None

    def get_forms(self) -> dict[str, set[str]]:
        """Get all possible forms of all words."""

        forms: dict[str, set[str]] = defaultdict(set)

        for word, item in self.__items.items():
            for form in item.definitions:
                for link_type, link in form.links:
                    forms[link].add(word)

        return forms


class Dictionaries:
    """A set of dictionaries for a language."""

    def __init__(self, dictionaries: Optional[list[Dictionary]] = None) -> None:
        self.dictionaries: list[Dictionary] = (
            [] if dictionaries is None else dictionaries
        )

    def add_dictionary(self, dictionary: Dictionary) -> None:
        """
        Add dictionary to the list.  It will have lower priority than previously
        added dictionaries.

        :param dictionary: dictionary to add
        """
        self.dictionaries.append(dictionary)

    def get_items(self, word: str) -> list[DictionaryItem]:
        """Get word definition from the first dictionary."""
        items: list[DictionaryItem] = []

        for dictionary in self.dictionaries:
            item: Optional[DictionaryItem] = dictionary.get_item(word)
            if item:
                items.append(item)
                links: set[str] = set()
                for definition in item.definitions:
                    links |= set([x.link_value for x in definition.links])
                for link in links:
                    link_item: DictionaryItem = dictionary.get_item(link)
                    if link_item:
                        items.append(link_item)
                return items

        return []
