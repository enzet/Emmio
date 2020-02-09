"""
Emmio.

Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
from typing import List, Optional

from emmio.util import error


class Dictionary:
    """
    Dictionary.
    """
    def __init__(self, file_name: str = None, file_format: str = None):
        """
        :param file_name: input dictionary file name.
        :param file_format: file format: `dict`, `json`, or `yaml`.
        """
        self.dictionary = {}

        if not file_name:
            self.file_name = None
            self.file_format = "dict"
            self.dictionary = {}

        self.file_name = file_name
        self.file_format = file_format
        if file_format == 'dict':
            key, value = '', ''
            with open(file_name) as file:
                lines = file.readlines()
                if file_name == 'mueller7.dict':
                    for line in lines:
                        line = line[:-1]
                        if len(line) > 0 and \
                                ('a' <= line[0] <= 'z' or 'A' <= line[
                                    0] <= 'Z'):
                            if key:
                                self.dictionary[key] = value
                            key = line
                            value = ''
                        else:
                            value += line + '\n'

                else:
                    for line in lines:
                        line = line[:-1]
                        if len(line) > 0 and line[0] not in ' \t':
                            if key:
                                self.dictionary[key] = value
                            key = line
                            value = ''
                        else:
                            value += line + '\n'

                if key:
                    self.dictionary[key] = value
        elif file_format == 'yaml':
            structure = yaml.load(open(file_name).read())
            if isinstance(structure, list):
                for element in structure:
                    if isinstance(element, list):
                        question = element[0]
                        answer = None
                        if len(element) > 2:
                            answer = element[1:]
                        else:
                            answer = element[1]
                        self.dictionary[question] = answer
                    else:
                        error('unknown YAML dictionary element format: ' +
                              str(element))
            elif isinstance(structure, dict):
                for question in structure:
                    answer = structure[question]
                    self.dictionary[question] = answer
        else:
            error(f"unknown dictionary format: {file_format}")

    def join(self, file_name: str, format_: str) -> None:
        new_dictionary = Dictionary(file_name, format_)
        for key in new_dictionary.dictionary:  # type: str
            if key not in self.dictionary:
                self.dictionary[key] = new_dictionary.dictionary[key]

    def add(self, word: str, definition: str) -> None:
        self.dictionary[word] = definition

    def set_file_name(self, file_name: str) -> None:
        self.file_name = file_name

    def write(self) -> None:
        with open(self.file_name, 'w+') as output:
            if self.file_format == "dict":
                for word in sorted(self.dictionary):
                    output.write(word + '\n')
                    output.write("    " + self.dictionary[word] + "\n")
            else:
                for word in sorted(self.dictionary):
                    output.write('"' + word + '": ')
                    output.write('"' + self.dictionary[word] + '"\n')

    def get(self, word: str) -> Optional[str]:
        if word in self.dictionary:
            return self.dictionary[word]
        return None

    def get_keys(self) -> List[str]:
        return list(self.dictionary.keys())

    def get_name(self) -> str:
        return self.file_name
