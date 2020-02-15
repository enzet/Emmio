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
        self.links = []
        self.images = []

        self.verb_group: Optional[int] = None

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

    def to_dict(self, write_en: bool = False) -> str:
        result = "  "
        type_ = self.type
        if self.type.startswith("form of "):
            result += "форма "
            type_ = type_[8:]
        if type_ == "verb":
            result += "гл."
        elif type_ == "preposition":
            result += "предл."
        else:
            result += type_
        result += "\n"
        if self.transcriptions or self.gender:
            result += "    "
        if self.transcriptions:
            result += ", ".join(
                map(lambda x: "[" + x + "]", sorted(self.transcriptions)))
        if self.gender:
            result += self.gender
        if self.verb_group:
            result += " " + str(self.verb_group) + " гр."
        if self.transcriptions or self.gender:
            result += "\n"
        if self.links:
            result += "    -> " + ", ".join(
                map(lambda x: "(" + x[0] + ") " + x[1], self.links)) + "\n"
        if self.translations["ru"]:
            result += "    " + ", ".join(sorted(self.translations["ru"])) + "\n"
        elif write_en and self.translations["en"]:
            result += "    (англ.) " + ", ".join(
                sorted(self.translations["en"])) + "\n"
        return result


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
