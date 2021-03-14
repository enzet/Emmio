"""
Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
import re
from iso639.iso639 import _Language as Language

from typing import Dict, List, Optional, Set

from emmio.ui import colorize


class Form:
    """
    Word form: noun, verb, etc.
    """
    def __init__(self, part_of_speech: str):
        self.part_of_speech: str = part_of_speech
        self.transcriptions: Set[str] = set()
        self.translations: Dict[str, Set] = {}
        self.links: List[(str, str)] = []

        # Optional characteristics.
        self.gender: Optional[str] = None
        self.verb_group: Optional[int] = None
        self.is_singular: Optional[bool] = None

    def add_transcription(self, transcription: str) -> None:
        """ Add word form IPA transcription. """
        self.transcriptions.add(transcription)

    def add_translations(self, translations: List[str], language: str) -> None:
        """
        Add word translations.  It is assumed that translations are sorted by
        usage frequency.

        :param language: language of translations
        :param translations: list of translations
        """
        if language not in self.translations:
            self.translations[language] = []
        self.translations[language] += translations

    def add_link(self, link_type: str, link: str) -> None:
        self.links.append((link_type, link))

    def set_gender(self, gender: str) -> None:
        """ Set gender of the form if has any. """
        self.gender = gender

    def set_verb_group(self, verb_group: int) -> None:
        self.verb_group = verb_group

    def to_dict(self) -> str:
        result = f"  {self.part_of_speech}\n"
        if self.transcriptions or self.gender:
            result += "    "
        if self.transcriptions:
            result += ", ".join(
                map(lambda x: f"[{x}]", sorted(self.transcriptions)))
        if self.gender:
            result += self.gender
        if self.verb_group:
            result += f" {self.verb_group!s} group"
        if self.is_singular is not None:
            if self.is_singular:
                result += " sing."
            else:
                result += " plur."
        if self.transcriptions or self.gender:
            result += "\n"
        if self.links:
            result += "    -> " + ", ".join(
                map(lambda x: "(" + x[0] + ") " + x[1], self.links)) + "\n"
        for language in self.translations:  # type: str
            if self.translations[language]:
                result += (
                    f"    [{language}]" +
                    ", ".join(sorted(self.translations[language])) + "\n")
        return result


class DictionaryItem:
    """
    Dictionary item: word translations.
    """
    def __init__(self, word: str):
        self.word: str = word
        self.definitions: List[Form] = []

    def add_definition(self, form: Form):
        """ Add word form to dictionary item. """
        self.definitions.append(form)

    def to_str(
            self, language: str, show_word: bool = True,
            use_colors: bool = False,
            hide_translations: Set[str] = None) -> str:
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
            desc = definition.part_of_speech
            if show_word and definition.transcriptions:
                desc += " " + ", ".join(map(
                    lambda x: f"/{x}/", definition.transcriptions))
            if definition.translations and language in definition.translations:
                translation_words = definition.translations[language]
                translation_words = set(filter(
                    lambda x:
                        (not hide_translations or
                         x.lower() not in hide_translations) and
                        x.lower() != self.word.lower(),
                    translation_words))
                if not show_word:
                    translation_words = map(
                        lambda x: x.replace(self.word, "_" * len(self.word)),
                        translation_words)
                    translation_words = map(
                        lambda x:
                            re.sub(" of [^ ]*", " of ?",
                            re.sub("\\([^)]*\\)", "--", x)),
                        translation_words)
                    translation_words = list(translation_words)
                if translation_words:
                    delimiter = (
                        "; " if max(map(len, translation_words)) < 25
                        else "\n    ")
                    result += colorize(desc, "grey") if use_colors else desc
                    result += (
                        "\n    " + delimiter.join(translation_words) + "\n")

        return result


class Dictionary:
    """ Dictionary of word definitions. """
    def __init__(self):
        self.__items: Dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        self.__items[word] = item

    def get_item(self, word: str) -> DictionaryItem:
        return self.__items[word]

    def get_forms(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for w in self.__items:  # type: str
            item = self.__items[w]
            for form_type in item.definitions:
                if form_type.startswith("form of "):
                    form = item.definitions[form_type]
                    for link_type, link in form.links:
                        if link not in result:
                            result[link] = set()
                        result[link].add(w)

        for key in result:  # type: str
            result[key] = list(result[key])

        return result


class Dictionaries:
    """ A set of dictionaries for a language. """
    def __init__(
            self, language: Language, dictionaries: List[Dictionary] = None):

        self.language: Language = language

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

    def get_translation(
            self, word: str, show_word: bool = True,
            translations_to_hide: Set[str] = None) -> str:
        """
        Get word definition from the first dictionary.
        """
        if translations_to_hide is None:
            translations_to_hide = set()

        for dictionary in self.dictionaries:  # type: Dictionary
            item: DictionaryItem = dictionary.get_item(word)
            if item:
                s = "\n"
                s += item.to_str(
                    self.language.part1, show_word, True, translations_to_hide) + "\n"
                s += "\n"
                links = set()
                for definition in item.definitions:
                    links |= set([x[1] for x in definition.links])
                for link in links:  # type: str
                    text = dictionary.get(
                        link, self.language.part1, show_word,
                        use_colors=True,
                        hide_translations=translations_to_hide)
                    if text:
                        s += link + "\n" if show_word else "-->\n"
                        s += (text + "\n")
                        s += "\n"
                return s
