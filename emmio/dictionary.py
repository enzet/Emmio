"""
Dictionary.
"""
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from emmio.ui import Interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class Link:
    link_type: str
    link: str

    def __hash__(self):
        return hash(f"{self.link_type}_{self.link}")


def hide(text: str, words_to_hide: list[str]) -> str:
    for word in words_to_hide:
        text = text.replace(word, "_" * len(word))
    return text


class Form:
    """
    Word form: noun, verb, etc.
    """

    def __init__(self, word: str, part_of_speech: str):
        self.word: str = word

        self.part_of_speech: str = part_of_speech
        self.transcriptions: set[str] = set()
        self.translations: dict[str, list[str]] = {}
        self.links: list[Link] = []

        # Optional characteristics.
        self.gender: Optional[str] = None
        self.verb_group: Optional[int] = None
        self.is_singular: Optional[bool] = None

    def add_transcription(self, transcription: str) -> None:
        """Add word form IPA transcription."""
        self.transcriptions.add(transcription)

    def add_translations(self, translations: list[str], language: str) -> None:
        """Add word translations."""
        for translation in translations:
            self.add_translation(translation, language)

    def add_translation(self, translation: str, language: str) -> None:
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

    def set_gender(self, gender: str) -> None:
        """Set gender of the form if has any."""
        self.gender = gender

    def set_verb_group(self, verb_group: int) -> None:
        """Set group if the word is a verb."""
        self.verb_group = verb_group

    def to_str(
        self,
        language: str,
        interface: Interface,
        show_word: bool = True,
        words_to_hide: set[str] = None,
        hide_translations: set[str] = None,
    ) -> str:
        """Get human-readable representation of the word form."""
        result: str = ""

        desc = self.part_of_speech
        if show_word and self.transcriptions:
            desc += " " + ", ".join(map(lambda x: f"{x}", self.transcriptions))

        if self.translations and language in self.translations:
            translations: list[str] = self.translations[language]
            translations = [
                x
                for x in translations
                if (not hide_translations or x.lower() not in hide_translations)
                and x.lower() != self.word.lower()
            ]

            # Hides words to hide.

            if not show_word and words_to_hide:
                translations = [
                    hide(x, list(words_to_hide)) for x in translations
                ]

            # Hide possible word forms.

            if not show_word:
                translations = [
                    re.sub("\\([^)]*\\)", "(░)", x) for x in translations
                ]
            if translations:
                delimiter = (
                    "; " if max(map(len, translations)) < 25 else "\n    "
                )
                result += interface.colorize(desc, "grey")
                result += "\n    " + delimiter.join(translations) + "\n"

        if self.links:
            for link in self.links:
                result += interface.colorize(desc, "grey")
                if show_word:
                    result += f"\n    -> {link.link_type} of {link.link}\n"
                else:
                    result += f"\n    -> {link.link_type}\n"

        return result


class DictionaryItem:
    """
    Dictionary item: word translations.
    """

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
        result: set[Link] = set()
        for definition in self.definitions:
            definition: Form
            for link in definition.links:
                result.add(link)
        return result

    def to_str(
        self,
        language: str,
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
                    links |= set([x.link for x in definition.links])
                for link in links:
                    link_item: DictionaryItem = dictionary.get_item(link)
                    if link_item:
                        items.append(link_item)
                return items

        return []
