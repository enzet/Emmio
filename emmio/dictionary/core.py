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

import asyncio
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Coroutine

from emmio.dictionary import CONFIG
from emmio.dictionary.config import DictionaryConfig
from emmio.language import Language, construct_language
from emmio.text_util import sanitize
from emmio.ui import Block, Colorized, Formatted, Interface, Text
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

    def to_text(self, to_hide: list[str] | None = None) -> Text:
        """Get human-readable form of definition.

        :param to_hide: list of words to be hidden from the output
        """

        value: str = self.value

        if to_hide is not None:
            value = sanitize(value, to_hide, SANITIZER)

        text: Text = Text()
        text.add(value)
        if self.description:
            text.add(Colorized(f" ({self.description})", "#AAAAAA"))

        return text


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

    @classmethod
    def from_simple_translation(cls, translation: str) -> "Definition":
        return cls([DefinitionValue.from_text(translation)])

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

    def to_text(self, to_hide: list[str] | None = None) -> Text | None:
        """Get human-readable form of definition.

        :param to_hide: list of words to be hidden from the output
        """
        if to_hide is not None and not self.is_common():
            return None

        text: Text = Text()

        if self.descriptors:
            text.add(
                Colorized("(" + ", ".join(self.descriptors) + ") ", "#AAAAAA")
            )

        for index, value in enumerate(self.values):
            text.add(value.to_text(to_hide))
            if index < len(self.values) - 1:
                text.add("; ")

        return text


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

    @classmethod
    def from_simple_translation(
        cls,
        word: str,
        language: Language,
        translation: str,
    ) -> "Form":
        return cls(
            word,
            None,
            set(),
            {language: [Definition.from_simple_translation(translation)]},
            [],
        )

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

    def to_text(
        self,
        language: Language,
        show_word: bool = True,
        words_to_hide: set[str] | None = None,
        hide_translations: set[str] | None = None,
        only_common: bool = True,
        max_definitions: int = 5,
    ) -> Text | None:
        """Get human-readable representation of the word form."""

        text: Text = Text()

        to_hide: list[str] | None = None

        if not show_word and words_to_hide and hide_translations:
            to_hide = sorted(
                list(words_to_hide | hide_translations), key=lambda x: -len(x)
            )

        description: list[str] = []
        if self.part_of_speech:
            description.append(self.part_of_speech)

        if show_word:
            if self.gender is not None:
                description.append(self.gender)
            if self.transcriptions:
                description.append(
                    ", ".join([f"{x}" for x in self.transcriptions])
                )

        definitions: list[Text] = []

        if self.definitions and language in self.definitions:
            for definition in self.definitions[language]:
                definition_text: Text | None = definition.to_text(to_hide)
                if definition_text is not None:
                    definitions.append(definition_text)

        if max_definitions:
            definitions = definitions[:max_definitions]

        links: list[Link] = self.get_links(only_common)

        if not definitions and not links:
            return None

        if description:
            text.add(
                Block(Colorized(" ".join(description), "#AAAAAA"), (0, 0, 0, 2))
            )

        if definitions:
            for definition in definitions:
                text.add(Block(definition, (0, 0, 0, 4)))

        for link in links:
            if show_word:
                link_text: Text = (
                    Text()
                    .add("-> ")
                    .add(Colorized(link.link_type + " of", "#AAAAAA"))
                    .add(" " + link.link_value)
                )
                text.add(Block(link_text, (0, 0, 0, 4)))
            else:
                text.add(Block(f"->{link.link_type}", (0, 0, 0, 4)))

        return text

    def get_links(self, only_common: bool = True):
        return [
            link for link in self.links if not only_common or link.is_common()
        ]


@dataclass
class DictionaryItem:
    """Dictionary item.

    Word with one etymology, that may have multiple forms.
    """

    word: str
    """Word being defined."""

    forms: list[Form] = field(default_factory=list)
    """Forms of the word."""

    etymology: str | None = None
    """Etymology explanation."""

    @classmethod
    def from_simple_translation(
        cls, word: str, language: Language, translation: str
    ) -> "DictionaryItem":
        return cls(
            word, [Form.from_simple_translation(word, language, translation)]
        )

    def add_form(self, form: Form) -> None:
        """Add word form to dictionary item."""
        self.forms.append(form)

    def set_etymology(self, etymology: str | None) -> None:
        """Set etymology explanation."""
        self.etymology = etymology

    def get_links(self) -> set[Link]:
        """Get keys to other dictionary items this dictionary item is linked
        to.
        """
        return set(
            [link for form in self.get_forms() for link in form.get_links()]
        )

    def get_forms(self) -> list[Form]:
        """Get all forms."""
        return self.forms

    def to_text(
        self,
        languages: list[Language],
        show_word: bool = True,
        words_to_hide: set[str] | None = None,
        hide_translations: set[str] | None = None,
        only_common: bool = True,
        max_definitions_per_form: int = 5,
    ) -> Text:
        """Get human-readable representation of the dictionary item.

        :param languages: the languages of translation
        :param show_word: if false, hide word transcription and word occurrences
            in examples
        :param words_to_hide: set of words to be hidden from the output
        :param hide_translations: list of translations that should be hidden
        :param only_common: return only common words
        :param max_definitions_per_form: maximum number of definitions to be
            returned for each form
        """
        text: Text = Text()

        if show_word:
            text.add(Block(Formatted(self.word, "bold"), (0, 0, 0, 2)))
            if self.etymology:
                text.add(
                    Block(
                        Colorized(
                            Formatted(self.etymology, "italic"), "#888888"
                        ),
                        (0, 0, 0, 2),
                    )
                )

        for form in self.get_forms():
            for language in languages:
                form_text: Text | None = form.to_text(
                    language,
                    show_word,
                    words_to_hide,
                    hide_translations,
                    only_common,
                    max_definitions_per_form,
                )
                if form_text is not None:
                    text.add(form_text)

        return text

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
        instead of first even if it is shorter.

        If the first value of the first form of the first definition is longer
        than the limit, it will be returned as is.

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

    async def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:
        """Get word definition."""

        if word in self.__items:
            return self.__items[word]

        return None

    async def get_items(self) -> dict[str, DictionaryItem]:
        """Get all dictionary items."""
        return self.__items

    async def get_items_marked(
        self,
        word: str,
        language: Language,
        ignore_words: set[str] | None = None,
        follow_links: bool = True,
    ) -> list[tuple["Dictionary", DictionaryItem]]:
        """Get dictionary items connected to the word.

        Get item for the word itself, and recursively items for links if
        `follow_links` is set.
        """

        if ignore_words and word in ignore_words:
            return []
        if not ignore_words:
            ignore_words = set()
        ignore_words.add(word)

        items_marked: list[tuple["Dictionary", DictionaryItem]] = []

        item: DictionaryItem | None = await self.get_item(word)
        if not item:
            return []

        items_marked.append((self, item))
        if not follow_links:
            return items_marked

        link_to_follow: set[str] = set(
            x.link_value
            for x in item.get_links()
            if x.link_value not in ignore_words
        )
        tasks: list[asyncio.Task[list[tuple["Dictionary", DictionaryItem]]]] = (
            []
        )
        for link_value in link_to_follow:
            coroutine: Coroutine[
                Any, Any, list[tuple["Dictionary", DictionaryItem]]
            ] = self.get_items_marked(
                link_value,
                language,
                ignore_words,
                follow_links,
            )
            tasks.append(asyncio.create_task(coroutine))

        results: list[list[tuple["Dictionary", DictionaryItem]]] = (
            await asyncio.gather(*tasks)
        )
        for result in results:
            items_marked += result

        return items_marked

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

    async def get_item(
        self, word: str, cache_only: bool = False
    ) -> DictionaryItem | None:
        if word not in self.data:
            return None

        item = DictionaryItem(word)
        definitions = [Definition([DefinitionValue(self.data[word])])]
        item.add_form(Form(word, definitions={self.to_language: definitions}))
        return item

    def check_from_language(self, language: Language) -> bool:
        return self.from_language == language

    def check_to_language(self, language: Language) -> bool:
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

    async def get_items_marked(
        self, word: str, language: Language, follow_links: bool = True
    ) -> list[tuple[Dictionary, DictionaryItem]]:
        """Get dictionary items from all dictionaries.

        :return: list of dictionaries and dictionary items
        """
        if not word:
            return []

        items_marked: list[tuple[Dictionary, DictionaryItem]] = []

        tasks: list = []
        for dictionary in self.dictionaries:
            coroutine = dictionary.get_items_marked(
                word,
                language,
                follow_links=follow_links,
            )
            tasks.append(asyncio.create_task(coroutine))

        result: list[list[tuple[Dictionary, DictionaryItem]]] = (
            await asyncio.gather(*tasks)
        )

        for main_items_marked in result:
            if not main_items_marked:
                continue
            items_marked += main_items_marked
            if not follow_links:
                continue
            for main_item_marked in main_items_marked:
                dictionary: Dictionary = main_item_marked[0]
                dictionary: Dictionary = main_item_marked[0]
                item: DictionaryItem = main_item_marked[1]
                links: set[str] = set()
                for form in item.get_forms():
                    links |= set([x.link_value for x in form.links])
                for link in links:
                    if link_item := await dictionary.get_item(link):
                        items_marked.append((dictionary, link_item))
                    if variant := language.get_variant(link):
                        if link_item := dictionary.get_item(variant):
                            items_marked.append((dictionary, link_item))

        # If the word may be written in different way, try to find this variant.
        if variant := language.get_variant(word):
            items_marked += await self.get_items_marked(variant, language)

        return items_marked

    async def get_items(
        self, word: str, language: Language, follow_links: bool = True
    ) -> list[DictionaryItem]:
        """Get dictionary records.

        :param word: the requested word
        :param language: the language of the word
        :param follow_links: include records for words linked to the requested
            word, e.g. include words the requested word is a form of
        """
        return [
            x[1]
            for x in await self.get_items_marked(word, language, follow_links)
        ]

    def get_dictionary(self, dictionary_id: str) -> Dictionary | None:
        for dictionary in self.dictionaries:
            if dictionary.id_ == dictionary_id:
                return dictionary

        return None

    async def to_text(
        self,
        word: str,
        language: Language,
        languages: list[Language],
    ) -> Text | None:
        """Get formatted dictionary items."""

        text: Text = Text()

        items: list[tuple[Dictionary, DictionaryItem]] = (
            await self.get_items_marked(word, language)
        )
        dictionary_name: str = ""

        for dictionary, item in items:
            if dictionary.get_name() != dictionary_name:
                dictionary_name = dictionary.get_name()
                text.add(dictionary_name)

            item_text: Text = item.to_text(languages)
            if item_text.is_empty():
                continue
            text.add(item_text)

        if text.is_empty():
            return None

        return text
