"""
Dictionary.
"""
import re
from typing import Dict, List, Optional, Set

from emmio.ui import colorize

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Form:
    """
    Word form: noun, verb, etc.
    """

    def __init__(self, word: str, part_of_speech: str):
        self.word: str = word

        self.part_of_speech: str = part_of_speech
        self.transcriptions: Set[str] = set()
        self.translations: Dict[str, List[str]] = {}
        self.links: List[(str, str)] = []

        # Optional characteristics.
        self.gender: Optional[str] = None
        self.verb_group: Optional[int] = None
        self.is_singular: Optional[bool] = None

    def add_transcription(self, transcription: str) -> None:
        """Add word form IPA transcription."""
        self.transcriptions.add(transcription)

    def add_translations(self, translations: List[str], language: str) -> None:
        """Add word translations."""
        for translation in translations:  # type: str
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

    def add_link(self, link_type: str, link: str) -> None:
        """
        Add link to another dictionary item if the word is a form of other word.

        :param link_type: link description, e.g. verb form
        :param link: other dictionary item key
        """
        self.links.append((link_type, link))

    def set_gender(self, gender: str) -> None:
        """Set gender of the form if has any."""
        self.gender = gender

    def set_verb_group(self, verb_group: int) -> None:
        """Set group if the word is a verb."""
        self.verb_group = verb_group

    def to_str(
        self,
        language: str,
        show_word: bool = True,
        use_colors: bool = True,
        hide_translations: Set[str] = None,
    ) -> str:
        """
        Get human-readable representation of the word form.
        """
        result: str = ""

        desc = self.part_of_speech
        if show_word and self.transcriptions:
            desc += " " + ", ".join(
                map(lambda x: f"/{x}/", self.transcriptions)
            )

        if self.translations and language in self.translations:
            translation_words = self.translations[language]
            translation_words = list(
                filter(
                    lambda x: (
                        not hide_translations
                        or x.lower() not in hide_translations
                    )
                    and x.lower() != self.word.lower(),
                    translation_words,
                )
            )
            if not show_word:
                translation_words = map(
                    lambda x: x.replace(self.word, "_" * len(self.word)),
                    translation_words,
                )
                translation_words = map(
                    lambda x: re.sub(
                        " of [^ ]*", " of ?", re.sub("\\([^)]*\\)", "--", x)
                    ),
                    translation_words,
                )
                translation_words = list(translation_words)
            if translation_words:
                delimiter = (
                    "; " if max(map(len, translation_words)) < 25 else "\n    "
                )
                result += colorize(desc, "grey") if use_colors else desc
                result += "\n    " + delimiter.join(translation_words) + "\n"

        if self.links:
            for link_type, link in self.links:
                result += colorize(desc, "grey") if use_colors else desc
                if show_word:
                    result += f"\n    -> {link_type} of {link}\n"
                else:
                    result += f"\n    -> {link_type}\n"

        return result


class DictionaryItem:
    """
    Dictionary item: word translations.
    """

    def __init__(self, word: str):
        self.word: str = word
        self.definitions: List[Form] = []

    def add_definition(self, form: Form):
        """Add word form to dictionary item."""
        self.definitions.append(form)

    def get_links(self) -> Set[str]:
        """
        Get keys to other dictionary items this dictionary item is linked to.
        """
        result: Set[str] = set()
        for definition in self.definitions:
            definition: Form
            for _, link in definition.links:
                result.add(link)
        return result

    def to_str(
        self,
        language: str,
        show_word: bool = True,
        use_colors: bool = True,
        hide_translations: Set[str] = None,
    ) -> str:
        """
        Get human-readable representation of the dictionary item.

        :param language: the language of translation
        :param show_word: if false, hide word transcription and word occurrences
            in examples
        :param use_colors: use colors to highlight different parts of dictionary
            item
        :param hide_translations: list of translations that should be hidden
        """
        result: str = ""

        for definition in self.definitions:  # type: Form
            result += definition.to_str(
                language, show_word, use_colors, hide_translations
            )

        return result


class Dictionary:
    """Dictionary of word definitions."""

    def __init__(self):
        self.__items: Dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        """Add word definition."""
        self.__items[word] = item

    def get_item(self, word: str) -> Optional[DictionaryItem]:
        """Get word definition."""
        if word in self.__items:
            return self.__items[word]

    def get_forms(self) -> Dict[str, Set[str]]:
        """Get all possible forms of all words."""
        result: Dict[str, Set[str]] = {}
        for word in self.__items:  # type: str
            item = self.__items[word]
            for form in item.definitions:
                for link_type, link in form.links:
                    if link not in result:
                        result[link] = set()
                    result[link].add(word)

        return result


class Dictionaries:
    """A set of dictionaries for a language."""

    def __init__(self, dictionaries: List[Dictionary] = None):

        self.dictionaries: List[Dictionary]
        if dictionaries is None:
            self.dictionaries = []
        else:
            self.dictionaries = dictionaries

    def add_dictionary(self, dictionary: Dictionary) -> None:
        """
        Add dictionary to the list.  It will have lower priority than previously
        added dictionaries.

        :param dictionary: dictionary to add
        """
        self.dictionaries.append(dictionary)

    def get_items(self, word: str) -> List[DictionaryItem]:
        """
        Get word definition from the first dictionary.
        """
        items: List[DictionaryItem] = []

        for dictionary in self.dictionaries:  # type: Dictionary
            item: DictionaryItem = dictionary.get_item(word)
            if item:
                items.append(item)
                links = set()
                for definition in item.definitions:
                    links |= set([x[1] for x in definition.links])
                for link in links:  # type: str
                    link_item: DictionaryItem = dictionary.get_item(link)
                    if link_item:
                        items.append(link_item)
                return items
