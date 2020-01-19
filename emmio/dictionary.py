"""
Emmio.

Dictionary.

Author: Sergey Vartanov (me@enzet.ru).
"""
import unittest

from emmio import reader


class Dictionary:
    """
    Dictionary.
    """
    def __init__(self, file_name: str=None, file_format: str=None):
        """
        :param file_name: input dictionary file name
        :param file_format: file format: `dict` or `yaml`
        """
        if file_name:
            self.file_name = file_name
            self.file_format = file_format
            self.dictionary = reader.read_dict(file_name, file_format)
        else:
            self.file_name = None
            self.file_format = "dict"
            self.dictionary = {}

    def join(self, file_name: str, format: str):
        new_dictionary = reader.read_dict(file_name, format)
        for key in new_dictionary:
            if key not in self.dictionary:
                self.dictionary[key] = new_dictionary[key]

    def add(self, word: str, definition: str):
        self.dictionary[word] = definition

    def set_file_name(self, file_name: str):
        self.file_name = file_name

    def write(self):
        with open(self.file_name, 'w+') as output:
            if self.file_format == "dict":
                for word in sorted(self.dictionary):
                    output.write(word + '\n')
                    output.write("    " + self.dictionary[word] + "\n")
            else:
                for word in sorted(self.dictionary):
                    output.write('"' + word + '": ')
                    output.write('"' + self.dictionary[word] + '"\n')

    def has(self, word: str):
        return word in self.dictionary

    def get(self, word: str):
        return self.dictionary[word]


class DictionaryTest(unittest.TestCase):
    def dictionary_test(self, file_name, format_):
        dictionary = Dictionary(file_name, format_)
        self.assertTrue(dictionary.has("книга"))
        self.assertTrue(dictionary.has("письмо"))
        self.assertFalse(dictionary.has("other"))
        self.assertEqual(dictionary.get("книга"), "    book\n")
        self.assertEqual(dictionary.get("письмо"), "    letter\n")

    def test_dictionary(self):
        self.dictionary_test("test/simple.dict", "dict"),
