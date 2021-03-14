"""
Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
import re
from iso639.iso639 import _Language as Language
import yaml

from typing import Dict, List, Optional, Set

from emmio.language import symbols
from emmio.ui import error, colorize


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

    to_update: bool = False

    def get(
            self, word: str, language: str, show_word: bool = True,
            hide_translations: Set[str] = None,
            use_colors: bool = False) -> Optional[str]:
        """
        Get word definition.
        """
        raise NotImplementedError()

    def get_name(self) -> str:
        """
        Get dictionary name.
        """
        raise NotImplementedError()


class SimpleDictionary(Dictionary):
    """
    Simple key to value mapping.
    """
    def __init__(
            self, from_language: str = None, file_name: str = None,
            file_format: str = None):
        """
        :param file_name: input dictionary file name.
        :param file_format: file format: `dict`, `json`, or `yaml`.
        """
        self.dictionary: Dict[str, str] = {}
        self.from_language = from_language

        if not file_name:
            self.file_name = None
            self.file_format = "dict"
            self.dictionary = {}

        if not file_format and file_name:
            if file_name.endswith(".json"):
                file_format = "json"
            if file_name.endswith(".dict"):
                file_format = "dict"
            if file_name.endswith(".yaml") or file_name.endswith(".yml"):
                file_format = "yaml"

        self.file_name = file_name
        self.file_format = file_format
        if file_format == "dict":
            key, value = "", ""
            with open(file_name) as file:
                lines = file.readlines()
                if file_name == "mueller7.dict":
                    for line in lines:
                        line = line[:-1]
                        if len(line) > 0 and \
                                ("a" <= line[0] <= "z" or "A" <= line[
                                    0] <= "Z"):
                            if key:
                                self.dictionary[key] = value
                            key = line
                            value = ""
                        else:
                            value += line + "\n"

                else:
                    for line in lines:
                        line = line[:-1]
                        if len(line) > 0 and line[0] not in " \t":
                            if key:
                                self.dictionary[key] = value
                            key = line
                            value = ""
                        else:
                            value += line + "\n"

                if key:
                    self.dictionary[key] = value
        elif file_format == "yaml":
            structure = yaml.load(
                open(file_name).read(), Loader=yaml.FullLoader)
            if isinstance(structure, list):
                for element in structure:
                    if isinstance(element, list):
                        question = element[0]
                        if len(element) > 2:
                            answer = element[1:]
                        else:
                            answer = element[1]
                        self.dictionary[question] = answer
                    else:
                        error(
                            f"unknown YAML dictionary element format: "
                            f"{element}")
            elif isinstance(structure, dict):
                for question in structure:
                    answer = structure[question]
                    self.dictionary[question] = answer
        else:
            error(f"unknown dictionary format: {file_format}")

    def to_structure(self) -> Dict[str, str]:
        return self.dictionary

    def join(self, file_name: str, format_: str) -> None:
        new_dictionary = SimpleDictionary(
            self.from_language, file_name, format_)
        for key in new_dictionary.dictionary:  # type: str
            if key not in self.dictionary:
                self.dictionary[key] = new_dictionary.dictionary[key]

    def add(self, word: str, definition: str) -> None:
        self.dictionary[word] = definition

    def set_file_name(self, file_name: str) -> None:
        self.file_name = file_name

    def write(self) -> None:
        with open(self.file_name, "w+") as output:
            if self.file_format == "dict":
                for word in sorted(self.dictionary):
                    output.write(word + "\n")
                    output.write("    " + self.dictionary[word] + "\n")
            else:
                for word in sorted(self.dictionary):
                    output.write(f'"{word}": ')
                    output.write(f'"{self.dictionary[word]}"\n')

    def get(
            self, word: str, language: str, show_word: bool = True,
            hide_translations: List[str] = None,
            use_colors: bool = False) -> Optional[str]:

        if word in self.dictionary:
            text: str = self.dictionary[word]
            if not show_word:
                text = re.sub("\\[.*\\]", "[" + "_" * len(word) + "]", text)
                # text = text.replace(word, "_" * len(word))
                new_text: str = ""
                for c in text:
                    if c in symbols[self.from_language]:
                        new_text += "_"
                    else:
                        new_text += c
                text = new_text
            return text

    def get_keys(self) -> List[str]:
        return list(self.dictionary.keys())

    def get_name(self) -> str:
        return self.file_name


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
            if "get_item" not in dir(dictionary):
                translation = dictionary.get(
                    word, self.language.part1, show_word, use_colors=True,
                    hide_translations=translations_to_hide)
                if translation:
                    return translation
            else:
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


class ExtendedDictionary(Dictionary):
    def __init__(self):
        self.items: Dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        self.items[word] = item

    def get(
            self, word: str, language: str, show_word: bool = True,
            hide_translations: List[str] = None, use_colors: bool = False):

        return self.get_item(word).to_str(
            language, show_word, use_colors=use_colors)

    def get_item(self, word: str) -> DictionaryItem:
        return self.items[word]

    def to_dict(self, write_unknown=True) -> str:
        result = ""
        for word in sorted(self.items):
            text = self.items[word].to_dict()
            if text:
                result += word + "\n"
                result += text
            elif write_unknown:
                result += word + "\n"
                result += "  ?\n"
        return result

    def update_links(self) -> None:
        for word in self.items:
            item = self.items[word]
            for form_type in item.forms:
                if not form_type.startswith("form of "):
                    continue
                link_form = form_type[len("form of "):]
                form = item.forms[form_type]
                for link_type, link in form.links:
                    if link not in self.items:
                        continue
                    link_item = self.items[link]
                    if link_form not in link_item.forms:
                        continue
                    translations = link_item.forms[link_form].translations
                    for language in translations:
                        form.add_translations(translations[language], language)
                    verb_group = link_item.forms[link_form].verb_group
                    form.set_verb_group(verb_group)

    def get_forms(self) -> Dict[str, Set[str]]:
        result: Dict[str, Set[str]] = {}
        for w in self.items:  # type: str
            item = self.items[w]
            for form_type in item.forms:
                if form_type.startswith("form of "):
                    form = item.forms[form_type]
                    for link_type, link in form.links:
                        if link not in result:
                            result[link] = set()
                        result[link].add(w)

        for key in result:  # type: str
            result[key] = list(result[key])

        return result
