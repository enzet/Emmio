"""
Frequency list utility.

Author: Sergey Vartanov (me@enzet.ru).
"""
import json
import random
from dataclasses import dataclass
from sqlite3 import Cursor
from typing import Dict, KeysView, List

import yaml

from emmio.database import Database
from emmio.ui import log, progress_bar


@dataclass
class WordOccurrences:
    """
    Unique word and number of its occurrences in some text.
    """
    word: str
    occurrences: int


class FrequencyList:
    """
    Frequency list of some text.
    """
    def __init__(self):
        self.data: Dict[str, int] = {}
        self.occurrences: int = 0
        self.sorted_keys: List[str] = []

    def __len__(self) -> int:
        return len(self.data)

    def read(self, file_name: str, file_format: str) -> None:
        """
        Read frequency list from the file.

        :param file_name: input file name.
        :param file_format: file format (`yaml`, `text`, or `json`).
        """
        if file_format == "yaml":
            self.read_yaml(file_name)
        elif file_format == "text":
            self.read_list(file_name)
        elif file_format == "json":
            self.read_json(file_name)
        else:
            raise Exception("unknown file format")

    def read_yaml(self, file_name: str) -> None:
        """
        Read file with frequency in the format:
        `<word>: <number of occurrences>`.

        :param file_name: input YAML file name.
        """
        log(f"Reading YAML frequency list from {file_name}...")

        try:
            self.read_list(file_name, ": ")
        except Exception:
            structure = yaml.load(open(file_name))

            for word in structure:
                self.data[word] = structure[word]

        self.sort()

    def read_json(self, file_name: str) -> None:
        """
        Read file with frequency in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param file_name: input JSON file name.
        """
        log(f"Reading JSON frequency list from {file_name}...")

        with open(file_name) as input_file:
            structure: List[(str, int)] = json.load(input_file)

        for word, occurrences in structure:
            word: str
            occurrences: int
            self.data[word] = int(occurrences)
            self.occurrences += occurrences

        self.sort()

    def read_list(self, file_name: str, delimiter: str = " ") -> None:
        """
        Read file with frequency in the format:
        `<word><delimiter><number of occurrences>`.

        :param file_name: input text file name.
        :param delimiter: delimiter between word and its number of occurrences.
        """
        log(f"reading frequency list from {file_name}")

        lines: List[str] = open(file_name).readlines()
        lines_number: int = len(lines)
        length: int = len(delimiter)

        for index, line in enumerate(lines):
            index: int
            line: str
            progress_bar(index, lines_number)
            position: int = line.find(delimiter)
            word: str = line[:position]
            occurrences: int = int(line[position + length:])
            self.data[word] = occurrences
            self.occurrences += occurrences

        progress_bar(-1, 0)

        self.sort()

    def write_list(self, file_name: str, delimiter: str = " ") -> None:
        """
        Write frequency list in the format:
        `<word><delimiter><number of occurrences>`.

        :param file_name: output text file name.
        :param delimiter: delimiter between word and its number of occurrences.
        """
        with open(file_name, "w+") as output_file:
            for word in sorted(self.data.keys(), key=lambda x: -self.data[x]):
                output_file.write(f"{word}{delimiter}{self.data[word]}\n")

    def write_json(self, file_name: str) -> None:
        """
        Write frequency list in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param file_name: output JSON file name.
        """
        structure: List = []
        for word in sorted(self.data.keys(), key=lambda x: -self.data[x]):
            word: str
            structure.append([word, self.data[word]])
        with open(file_name, 'w+') as output:
            json.dump(structure, output, indent=4, ensure_ascii=False)

    def add(self, word: str, occurrences: int = 1) -> None:
        """ Add word and its occurrences in some text. """
        if word not in self.data:
            self.data[word] = 0

        self.data[word] += occurrences
        self.occurrences += occurrences
        self.sorted_keys = None

    def ignore_proper_nouns(self) -> None:
        """ Make frequency list case-insensitive. """
        for word in self.data.keys():
            word: str
            if word.lower() != word:
                if word.lower() in self.data:
                    self.data[word.lower()] += self.data[word]
                del self.data[word]
        self.sort()

    def has(self, word: str) -> bool:
        """ Check whether frequency list contains word. """
        return word in self.data

    def get_occurrences(self, word: str) -> int:
        """ Get number of word occurrences in text. """
        if word in self.data:
            return self.data[word]
        return 0

    def get_position(self, word: str) -> int:
        """
        Get word index in frequency list.  The most popular word in the text has
        index 1.  If word is not in frequency list, return -1.
        """
        if word in self.sorted_keys:
            return self.sorted_keys.index(word)
        return -1

    def get_all_occurrences(self) -> int:
        """ Get number of all words in the text. """
        return self.occurrences

    def get_words(self):
        """ Get all unique words. """
        return sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word(self) -> (str, int):
        """
        Return random unique word regardless of its frequency.

        :return word, number of its occurrences in text
        """
        word = random.choice(list(self.data.keys()))
        return word, self.data[word]

    def get_word_by_occurrences(self, occurrences: int) -> (str, int):
        """
        Get first word with the number of occurrences more or equals to
        specified number.

        :return word and its number of occurrences in the text
        """
        for word in self.sorted_keys:
            if self.data[word] >= occurrences:
                return word, self.data[word]

    def get_word_by_index(self, index: int) -> (str, int):
        """ Get word of the specified index. """
        word: str = self.sorted_keys[index]
        return word, self.data[word]

    def sort(self) -> None:
        """ Sort keys by frequency. """
        self.sorted_keys = sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word_by_frequency(self) -> (str, int):
        """
        Return random word based on its frequency as if you pick up random word
        from the text.

        :return word, number of its occurrences in text
        """
        number = random.randint(0, self.occurrences)

        if not self.sorted_keys:
            self.sort()

        index = 0
        for word in self.sorted_keys:
            index += self.data[word]
            if index >= number:
                return word, self.data[word]

        return "", 0


class FrequencyDatabase(Database):
    """
    Database that contains frequency list tables.  Table format:

        ID INTEGER PRIMARY KEY
        WORD TEXT
        FREQUENCY INTEGER
    """
    def get_words(self, frequency_list_id: str) -> Cursor:
        """
        Get all records from the table in the format of (ID, WORD, FREQUENCY).
        """
        return self.cursor.execute(f"SELECT * FROM {frequency_list_id}")

    def add_table(self, table_id: str, frequency_list: FrequencyList):
        """
        Add new table to the database and fill it with the data from frequency
        list.
        """
        if self.has_table(table_id):
            raise Exception()
        self.cursor.execute(
            f"CREATE TABLE {table_id} ("
            f"ID INTEGER PRIMARY KEY, "
            f"WORD TEXT, "
            f"FREQUENCY INTEGER)"
        )
        for index, word in enumerate(frequency_list.get_words()):
            index: int
            word: str
            occurrences: int = frequency_list.get_occurrences(word)
            self.cursor.execute(
                f"INSERT INTO {table_id} VALUES (?,?,?)",
                (index, word, occurrences)
            )
        self.connection.commit()
