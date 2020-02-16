"""
Emmio.

Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
import yaml

from typing import Dict, List, Optional, Set

from emmio.util import error


class Form:
    """
    Word form: noun, verb, etc.
    """

    def __init__(self, type_: str):
        self.type = type_
        self.gender: Optional[str] = None
        self.transcriptions: Set[str] = set()
        self.translations: Dict[str, Set] = {}
        self.links: List[(str, str)] = []

        self.verb_group: Optional[int] = None
        self.is_singular: Optional[bool] = None

    def add_transcription(self, transcription: str) -> None:
        self.transcriptions.add(transcription)

    def add_translations(self, translations: Set, language: str) -> None:
        if language not in self.translations:
            self.translations[language] = set()
        self.translations[language] = \
            self.translations[language].union(translations)

    def add_link(self, link_type: str, link: str) -> None:
        self.links.append((link_type, link))

    def set_gender(self, gender: str) -> None:
        self.gender = gender

    def set_verb_group(self, verb_group: int) -> None:
        self.verb_group = verb_group

    def to_dict(self) -> str:
        result = f"  {self.type}\n"
        if self.transcriptions or self.gender:
            result += "    "
        if self.transcriptions:
            result += ", ".join(
                map(lambda x: "[" + x + "]", sorted(self.transcriptions)))
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
                result += f"    [{language}]" + \
                    ", ".join(sorted(self.translations[language])) + "\n"
        return result


class DictionaryItem:
    def __init__(self, word: str):
        self.word: str = word
        self.forms: Dict[str, Form] = {}

    def set_gender(self, form_type: str, gender: str) -> None:
        if form_type not in self.forms:  # type: str
            self.forms[form_type] = Form(form_type)
        self.forms[form_type].set_gender(gender)

    def add_transcription(self, form_type: str, transcription: str) -> None:
        if form_type not in self.forms:  # type: str
            self.forms[form_type] = Form(form_type)
        self.forms[form_type].add_transcription(transcription)

    def add_translations(self, form_type: str, translations: set,
                         language: str) -> None:

        if form_type not in self.forms:  # type: str
            self.forms[form_type] = Form(form_type)
        self.forms[form_type].add_translations(translations, language)

    def add_link(self, form_type: str, link_type: str, link: str) -> None:
        if form_type not in self.forms:  # type: str
            self.forms[form_type] = Form(form_type)
        self.forms[form_type].add_link(link_type, link)

    def set_verb_group(self, verb_group) -> None:
        if "verb" not in self.forms:  # type: str
            form = Form("verb")
            form.set_verb_group(verb_group)
            self.forms["verb"] = form

    def to_dict(self):
        result = ""
        for form_type in sorted(self.forms):
            result += self.forms[form_type].to_dict()
        return result

    def __repr__(self) -> str:
        return str(self.to_dict())


class Dictionary:
    def get(self, word: str) -> Optional[str]:
        """
        Get word definition.
        """
        pass

    def get_name(self) -> str:
        """
        Get dictionary name.
        """
        pass


class SimpleDictionary(Dictionary):
    """
    Simple key to value mapping.
    """
    def __init__(self, file_name: str = None, file_format: str = None):
        """
        :param file_name: input dictionary file name.
        :param file_format: file format: `dict`, `json`, or `yaml`.
        """
        self.dictionary: Dict[str, str] = {}

        if not file_name:
            self.file_name = None
            self.file_format = "dict"
            self.dictionary = {}

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
            structure = yaml.load(open(file_name).read())
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
                        error(f"unknown YAML dictionary element format: "
                            f"{element!s}")
            elif isinstance(structure, dict):
                for question in structure:
                    answer = structure[question]
                    self.dictionary[question] = answer
        else:
            error(f"unknown dictionary format: {file_format}")

    def to_structure(self) -> Dict[str, str]:
        return self.dictionary

    def join(self, file_name: str, format_: str) -> None:
        new_dictionary = SimpleDictionary(file_name, format_)
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

    def get(self, word: str) -> Optional[str]:
        if word in self.dictionary:
            return self.dictionary[word]
        return None

    def get_keys(self) -> List[str]:
        return list(self.dictionary.keys())

    def get_name(self) -> str:
        return self.file_name

class ExtendedDictionary(Dictionary):
    def __init__(self):
        self.items: Dict[str, DictionaryItem] = {}

    def add(self, word: str, item: DictionaryItem) -> None:
        self.items[word] = item

    def get(self, word: str) -> DictionaryItem:
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
