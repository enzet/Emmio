"""
Emmio.

Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
from emmio import reader


class Dictionary:
    """
    Dictionary.
    """
    def __init__(self, file_name: str = None, file_format: str = None) -> None:
        """
        :param file_name: input dictionary file name.
        :param file_format: file format: `dict`, `json`, or `yaml`.
        """
        if file_name:
            self.file_name = file_name
            self.file_format = file_format
            self.dictionary = reader.read_dict(file_name, file_format)
        else:
            self.file_name = None
            self.file_format = "dict"
            self.dictionary = {}

    def join(self, file_name: str, format_: str) -> None:
        new_dictionary = reader.read_dict(file_name, format_)
        for key in new_dictionary:  # type: str
            if key not in self.dictionary:
                self.dictionary[key] = new_dictionary[key]

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

    def has(self, word: str) -> bool:
        return word in self.dictionary

    def get(self, word: str) -> str:
        return self.dictionary[word]
