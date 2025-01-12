"""Dictionary.

Collection of words and their definitions.

Dictionary: collection of all items.
  - Dictionary items: definition for a word.
      - Forms: word form.
          - Part of speech.
          - Transcriptions: IPA transcriptions.
          - Definitions: definition of the word form.
              - Definition value: definition value.
          - Links: link to another word.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from emmio.dictionary import CONFIG
from emmio.dictionary.config import DictionaryConfig
from emmio.language import Language, construct_language
from emmio.text_util import sanitize
from emmio.ui import Interface
from emmio.util import flatten

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


DESCRIPTORS_OF_WORDS_TO_IGNORE: set[str] = set(
    CONFIG["descriptors_of_words_to_ignore"]
)
SANITIZER: str = "_"


class WordStatus(Enum):
    """How the word is presented in the dictionary."""

    COMMON = "common"
    """The word is the common word in dictionary. E.g. `book`."""

    FORM = "form"
    """The word is only a form of another common word in dictionary.
    
    E.g. `books` is either a plural form of the noun `book` or a form of a verb
    `book`."""

    NOT_COMMON = "not_common"
    """The word is not common.
    
    It may be a letter, a proper noun, an abbreviation, etc."""

    NO_DEFINITION = "no_definition"
    """The dictionary has no definition for the word."""


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
class Audio:
    url: str


@dataclass
class Definition:
    """Definition of a word.

    If the language of the word and the definition differ, the definition is
    a translation.
    """

    values: list[DefinitionValue]
    """Definition values."""

    descriptors: list[str] = field(default_factory=list)
    """Descriptors of the definition (e.g. "slang", "colloquial", etc.)."""

    def is_common(self) -> bool:
        """
        Check whether this definition is common.

        Meaning is not
            - slang, colloquial,
            - obsolete, etc.
        """
        for descriptor in DESCRIPTORS_OF_WORDS_TO_IGNORE:
            if descriptor in self.descriptors:
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

        # FIXME: hack for the Ukrainian.
        if to_hide and "•" in result:
            return "•••"

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
        """Add word translation.

        It is assumed that translations are sorted by usage frequency.

        :param language: language of translation
        :param translation: word translation
        """
        if language not in self.definitions:
            self.definitions[language] = []
        self.definitions[language].append(translation)

    def add_link(self, link: Link) -> None:
        """Add link to another dictionary item if the word is a form.

        :param link: link to another dictionary item
        """
        self.links.append(link)

    def is_not_common(self, language: Language) -> bool:
        """Check whether we can deduce from the present definitions that word is
        not a common word of the language. E.g. it is misspelling, obsolete, or
        slang.

        Also check whether it is just a form of some another word.
        """
        if self.part_of_speech == "letter":
            return True

        if language in self.definitions:
            for definition in self.definitions[language]:
                if definition.is_common():
                    return False
            return True

        # If there are no definitions, but there are links to other forms, we
        # decide that this is just a form of a word.
        if self.links:
            return True

        # If there are no definitions and no links, we cannot decide if the word
        # is not # common.
        return False

    def to_str(
        self,
        language: Language,
        interface: Interface,
        show_word: bool = True,
        words_to_hide: set[str] = None,
        hide_translations: set[str] = None,
        only_common: bool = True,
        max_definitions: int = 5,
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

        if max_definitions:
            definitions = definitions[:max_definitions]

        links: list[Link] = self.get_links(only_common)

        if not definitions and not links:
            return ""

        result: str = "  " + interface.colorize(description, "grey") + "\n"

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
class Etymology:
    forms: list[Form] = field(default_factory=list)


@dataclass
class DictionaryItem:
    """Dictionary item.

    Word with one etymology, that may have multiple forms.
    """

    word: str
    general_etymology: Etymology = field(default_factory=Etymology)
    etymologies: list[Etymology] = field(default_factory=list)

    def add_form(self, form: Form):
        """Add word form to dictionary item."""
        self.get_forms().append(form)

    def get_links(self) -> set[Link]:
        """Get keys to other dictionary items this dictionary item is linked
        to.
        """
        return set(
            [link for form in self.get_forms() for link in form.get_links()]
        )

    def get_forms(self) -> list[Form]:
        """Get all forms in all etymologies."""
        forms: list[Form] = self.general_etymology.forms
        for etymology in self.etymologies:
            forms += etymology.forms
        return forms

    def to_str(
        self,
        languages: list[Language],
        interface: Interface,
        show_word: bool = True,
        words_to_hide: set[str] | None = None,
        hide_translations: set[str] | None = None,
        only_common: bool = True,
        max_definitions_per_form: int = 5,
    ) -> str:
        """Get human-readable representation of the dictionary item.

        :param languages: the languages of translation
        :param interface: user interface provider
        :param show_word: if false, hide word transcription and word occurrences
            in examples
        :param words_to_hide: set of words to be hidden from the output
        :param hide_translations: list of translations that should be hidden
        :param only_common: return only common words
        :param max_definitions_per_form: maximum number of definitions to be
            returned for each form
        """
        result: str = ""

        if show_word:
            result += "  " + self.word + "\n"

        for form in self.get_forms():
            for language in languages:
                result += form.to_str(
                    language,
                    interface,
                    show_word,
                    words_to_hide,
                    hide_translations,
                    only_common,
                    max_definitions_per_form,
                )

        return result

    def has_definitions(self) -> bool:
        """Check whether the dictionary item has at least one definition."""
        return len(self.get_forms()) > 0

    def is_not_common(self, language: Language) -> bool:
        """Check whether all forms of the word are not common.

        Also check if it is not just a form of some another word.
        """
        for form in self.get_forms():
            if not form.is_not_common(language):
                return False

        return True

    def get_one_word_definitions(self, language: Language) -> list[str]:
        result: list[str] = []

        for form in self.get_forms():
            if language in form.definitions:
                for definition in form.definitions[language]:
                    for value in definition.values:
                        if " " not in value.value and value.value not in result:
                            result.append(value.value)

        return result

    def get_short(self, language: Language, limit: int = 80) -> tuple[str, str]:
        """Try to get word definition that is shorter than the selected limit.

        This method is trying to remove values, remove definitions and
        eventually remove forms to fit the specified limit.  It assumes that
        values, definitions and forms are ordered by its usage frequency or
        some kind of importance, so it is not trying to use second definition
        instead of first if it is shorter.

        If the first value of the first form of the first definition is longer
        than the limit, it will return it as is.

        :returns (transcription, translation)
        """
        # Forms, definitions, values.
        texts: list[list[list[str]]] = []
        transcription = ""

        for form in self.get_forms():
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
        for form in self.get_forms():
            for transcription in form.transcriptions:
                if transcription not in result:
                    result.append(transcription)
        return result


class Dictionary:
    """Dictionary of word definitions."""

    def __init__(self, id_: str) -> None:
        self.id_: str = id_
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

    def get_items(self) -> dict[str, DictionaryItem]:
        return self.__items

    def get_forms(self) -> dict[str, set[str]]:
        """Get all possible forms of all words."""

        forms: dict[str, set[str]] = defaultdict(set)

        for word, item in self.__items.items():
            for form in item.get_forms():
                for link_type, link in form.links:
                    forms[link].add(word)

        return forms

    def check_from_language(self, language: Language) -> bool:
        raise NotImplementedError()

    def check_to_language(self, language: Language) -> bool:
        raise NotImplementedError()

    def get_name(self) -> str:
        raise NotImplementedError()


class SimpleDictionary(Dictionary):
    def __init__(
        self,
        id_: str,
        path: Path,
        name: str,
        data: dict[str, str],
        from_language: Language,
        to_language: Language,
    ) -> None:
        super().__init__(id_)
        self.path: Path = path
        self.name: str = name
        self.data: dict[str, str] = data
        self.from_language: Language = from_language
        self.to_language: Language = to_language

    def add_simple(self, word: str, definition: str) -> None:
        self.data[word] = definition

    @classmethod
    def from_config(
        cls, path: Path, id_: str, config: DictionaryConfig
    ) -> "SimpleDictionary":
        with (path / config.file_name).open() as input_file:
            data: dict[str, str] = json.load(input_file)

        return cls(
            id_,
            path / config.file_name,
            config.name,
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
        item.add_form(Form(word, definitions={self.to_language: definitions}))
        return item

    def check_from_language(self, language: Language) -> Language:
        return self.from_language == language

    def check_to_language(self, language: Language) -> Language:
        return self.to_language == language

    def write(self):
        print(f"dumped to {self.path}")
        with self.path.open("w") as output_file:
            json.dump(
                self.data,
                output_file,
                ensure_ascii=False,
                indent=4,
                sort_keys=True,
            )

    def get_name(self) -> str:
        return self.name


@dataclass
class DictionaryCollection:
    """A set of dictionaries for a language."""

    dictionaries: list[Dictionary] = field(default=list)

    def add_dictionary(self, dictionary: Dictionary) -> None:
        """Add dictionary to the list.

        It will have lower priority than previously added dictionaries.
        """
        self.dictionaries.append(dictionary)

    def get_items_marked(
        self, word: str, language: Language, follow_links: bool = True
    ) -> list[tuple[Dictionary, DictionaryItem]]:
        """Get dictionary items from all dictionaries."""

        if not word:
            return []

        items: list[tuple[Dictionary, DictionaryItem]] = []

        for dictionary in self.dictionaries:
            if item := dictionary.get_item(word):
                items.append((dictionary, item))
                if not follow_links:
                    continue
                links: set[str] = set()
                for form in item.get_forms():
                    links |= set([x.link_value for x in form.links])
                for link in links:
                    if link_item := dictionary.get_item(link):
                        items.append((dictionary, link_item))
                    if variant := language.get_variant(link):
                        if link_item := dictionary.get_item(variant):
                            items.append((dictionary, link_item))

        # If the word may be written in different way, try to find this variant.
        if variant := language.get_variant(word):
            items += self.get_items_marked(variant, language)

        return items

    def get_items(
        self, word: str, language: Language, follow_links: bool = True
    ) -> list[DictionaryItem]:
        """Get dictionary records.

        :param word: the requested word
        :param language: the language of the word
        :param follow_links: include records for words linked to the requested
            word, e.g. include words the requested word is a form of
        """
        return [
            x[1] for x in self.get_items_marked(word, language, follow_links)
        ]

    def get_dictionary(self, dictionary_id: str) -> Dictionary | None:
        for dictionary in self.dictionaries:
            if dictionary.id_ == dictionary_id:
                return dictionary

        return None

    def to_str(self, word, language, languages, interface) -> str:
        items: list[tuple[Dictionary, DictionaryItem]] = self.get_items_marked(
            word, language
        )
        dictionary_name: str = ""
        result = ""
        for dictionary, item in items:
            if dictionary.get_name() != dictionary_name:
                dictionary_name = dictionary.get_name()
                result += dictionary_name + "\n"
            result += item.to_str(languages, interface) + "\n"

        return result
