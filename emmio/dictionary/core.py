"""Dictionary."""
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from emmio.dictionary.config import DictionaryConfig
from emmio.language import Language, construct_language
from emmio.text import sanitize
from emmio.ui import Interface
from emmio.util import flatten

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


SANITIZER: str = "_"

DESCRIPTORS_OF_WORDS_TO_IGNORE: list[str] = [
    "archaic",
    "colloquial",  # TODO: remove
    "dated",
    "figuratively",
    "informal",  # TODO: remove
    "obsolete",
    "rare",
    "slang",
    "spelling",
    "US",
    "Philippines",
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

    def to_str(self, to_hide: list[str] | None = None) -> str | None:
        """Get human-readable form of definition."""

        value: str = self.value

        if to_hide is not None:
            value = sanitize(value, to_hide, SANITIZER)

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

    def to_str(self, to_hide: list[str] | None = None) -> str | None:
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

    part_of_speech: str = "unknown"
    transcriptions: set[str] = field(default_factory=set)
    definitions: dict[Language, list[Definition]] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)

    # Optional characteristics.
    gender: str | None = None
    verb_group: int | None = None
    is_singular: bool | None = None

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
        Add word translation.

        It is assumed that translations are sorted by usage frequency.

        :param language: language of translation
        :param translation: word translation
        """
        if language not in self.definitions:
            self.definitions[language] = []
        self.definitions[language].append(translation)

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

        if language in self.definitions:
            for definition in self.definitions[language]:
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
        to_hide: list[str] | None = None

        if not show_word:
            to_hide = sorted(
                list(words_to_hide | hide_translations), key=lambda x: -len(x)
            )

        description: str = self.part_of_speech
        if show_word and self.transcriptions:
            if self.gender is not None:
                description += f" {self.gender}"
            description += " " + ", ".join(
                [f"{x}" for x in self.transcriptions]
            )

        definitions: list[str] = []

        if self.definitions and language in self.definitions:
            for translation in self.definitions[language]:
                string: str | None = translation.to_str(to_hide)
                if string is not None and string not in definitions:
                    definitions.append(string)

        links: list[Link] = self.get_links(only_common)

        if not definitions and not links:
            return ""

        result: str = interface.colorize(description, "grey") + "\n"

        if definitions:
            result += "    " + "\n    ".join(definitions) + "\n"

        for link in links:
            if show_word:
                result += f"    → {link.link_type} of {link.link_value}\n"
            else:
                result += f"    → {link.link_type}\n"

        return result

    def get_links(self, only_common: bool = True):
        return [
            link for link in self.links if not only_common or link.is_common()
        ]


@dataclass
class DictionaryItem:
    """Dictionary item: word translations."""

    word: str
    forms: list[Form] = field(default_factory=list)

    def add_definition(self, form: Form):
        """Add word form to dictionary item."""
        self.forms.append(form)

    def get_links(self) -> set[Link]:
        """
        Get keys to other dictionary items this dictionary item is linked to.
        """
        return set([link for form in self.forms for link in form.get_links()])

    def to_str(
        self,
        language: Language,
        interface: Interface,
        show_word: bool = True,
        words_to_hide: set[str] | None = None,
        hide_translations: set[str] | None = None,
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

        for definition in self.forms:
            result += definition.to_str(
                language, interface, show_word, words_to_hide, hide_translations
            )

        return result

    def has_definitions(self) -> bool:
        """Check whether the dictionary item has at least one definition."""
        return len(self.forms) > 0

    def has_common_definition(self, language: Language) -> bool:
        """
        Check whether the form has at least one common definition.

        Also check if it is not just a form of some another word.
        """
        for definition in self.forms:
            if definition.has_common_definition(language):
                return True

        return False

    def get_short(self, language: Language, limit: int = 80) -> tuple[str, str]:
        """
        Try to get word definition that is shorter than the selected limit.

        This method is trying to remove values, remove definitions and
        eventually remove forms to fit the specified limit.  It assumes that
        values, definitions and forms are ordered by its usage frequency or
        some kind of importance, so it is not trying to use second definition
        instead of first if it is shorter.

        If the first value of the first form of the first definition is longer
        than the limit, it will return it as is.
        """
        # Forms, definitions, values.
        texts: list[list[list[str]]] = []
        transcription = ""

        for form in self.forms:
            if language not in form.definitions:
                continue
            definitions: list[list[str]] = []

            for link in form.get_links():
                definitions.append(["→ " + link.link_value])
            for definition in form.definitions[language]:
                definitions.append([value.value for value in definition.values])
            texts.append(definitions)
            if not transcription and form.transcriptions:
                transcription = list(form.transcriptions)[0]

        for limit_1, limit_2, limit_3 in (2, 2, 2), (2, 2, 1), (2, 1, 1):
            if len(text := flatten(texts, limit_1, limit_2, limit_3)) < limit:
                return transcription, text

        return transcription, flatten(texts, 1, 1, 1)

    def get_transcriptions(self) -> list[str]:
        result: list[str] = []
        for form in self.forms:
            for transcription in form.transcriptions:
                if transcription not in result:
                    result.append(transcription)
        return result


class Dictionary:
    """Dictionary of word definitions."""

    def __init__(self) -> None:
        self.__items: dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        """Add word definition."""
        self.__items[word] = item

    def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:
        """Get word definition."""

        if word in self.__items:
            return self.__items[word]

        return None

    def get_forms(self) -> dict[str, set[str]]:
        """Get all possible forms of all words."""

        forms: dict[str, set[str]] = defaultdict(set)

        for word, item in self.__items.items():
            for form in item.forms:
                for link_type, link in form.links:
                    forms[link].add(word)

        return forms

    def check_from_language(self, language: Language) -> bool:
        raise NotImplementedError()

    def check_to_language(self, language: Language) -> bool:
        raise NotImplementedError()


@dataclass
class SimpleDictionary(Dictionary):

    data: dict[str, str]
    from_language: Language
    to_language: Language

    @classmethod
    def from_config(
        cls, path: Path, config: DictionaryConfig
    ) -> "SimpleDictionary":

        with (path / config.file_name).open() as input_file:
            data = json.load(input_file)

        return cls(
            data,
            construct_language(config.from_language),
            construct_language(config.to_language),
        )

    def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:

        if word not in self.data:
            return None

        item = DictionaryItem(word)
        definitions = [Definition([DefinitionValue(self.data[word])])]
        item.add_definition(
            Form(word, definitions={self.to_language: definitions})
        )
        return item

    def check_from_language(self, language: Language) -> Language:
        return self.from_language == language

    def check_to_language(self, language: Language) -> Language:
        return self.to_language == language


class DictionaryCollection:
    """A set of dictionaries for a language."""

    def __init__(self, dictionaries: list[Dictionary] | None = None) -> None:
        self.dictionaries: list[Dictionary] = (
            [] if dictionaries is None else dictionaries
        )

    def add_dictionary(self, dictionary: Dictionary) -> None:
        """
        Add dictionary to the list.

        It will have lower priority than previously added dictionaries.
        """
        self.dictionaries.append(dictionary)

    def get_items(self, word: str) -> list[DictionaryItem]:
        """Get dictionary items from all dictionaries."""

        items: list[DictionaryItem] = []

        for dictionary in self.dictionaries:
            if item := dictionary.get_item(word):
                items.append(item)
                links: set[str] = set()
                for definition in item.forms:
                    links |= set([x.link_value for x in definition.links])
                for link in links:
                    link_item: DictionaryItem = dictionary.get_item(link)
                    if link_item:
                        items.append(link_item)

        return items
