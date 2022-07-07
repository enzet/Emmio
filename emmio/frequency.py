"""
Frequency list utility.
"""
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Cursor
from typing import Any, Optional

import urllib3
import yaml
from urllib3 import HTTPResponse

from emmio.database import Database
from emmio.ui import progress_bar

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.util import MalformedFile


@dataclass
class WordOccurrences:
    """Unique word and number of its occurrences in some text."""

    word: str
    occurrences: int


class FrequencyList:
    """Frequency list of some text."""

    def __init__(self, update: bool):
        self.data: dict[str, int] = {}
        self.occurrences: int = 0
        self.sorted_keys: list[str] = []
        self.update: bool = update

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def from_structure(
        cls, structure: dict[str, Any], directory: Path
    ) -> Optional["FrequencyList"]:
        """Construct frequency list from description."""

        update: bool = False
        if "update" in structure:
            update = structure["update"]

        cache_path: Path = directory / f'{structure["id"]}.json'

        if cache_path.exists():
            return cls.from_json_file(cache_path, update)

        temp_path: Path = directory / f'{structure["id"]}.tmp'

        if "url" in structure:
            pool_manager = urllib3.PoolManager()
            result: HTTPResponse = pool_manager.request(
                "GET", structure["url"], preload_content=False
            )
            pool_manager.clear()
            data: bytearray = bytearray()
            sys.stdout.write("Downloading: ")
            while True:
                buffer = result.read(400_000)
                sys.stdout.write("█")
                sys.stdout.flush()
                if not buffer:
                    break
                data.extend(buffer)
            sys.stdout.write("\n")

            with temp_path.open("wb+") as temp_file:
                temp_file.write(data)

            (
                frequency_list := cls.from_file(temp_path, structure, update)
            ).write_json(cache_path)
            return frequency_list

        if "path" in structure:
            return cls.from_file(Path(structure["path"]), structure, update)

    @classmethod
    def from_file(
        cls, file_path: Path, structure: dict[str, Any], update: bool
    ) -> "FrequencyList":
        """
        Read frequency list from the file.

        :param file_path: input file name.
        :param structure: structure describing file format.
        :param update: whether source file is constantly updated.
        """
        if structure["format"] == "yaml":
            return cls.from_yaml_file(file_path, update)
        elif structure["format"] == "list":
            return cls.from_list_file(file_path, structure["delimiter"], update)
        elif structure["format"] == "word_list":
            return cls.from_word_list_file(file_path, update)
        elif structure["format"] == "csv":
            return cls.from_csv_file(
                file_path, structure["header"], structure["delimiter"], update
            )
        elif structure["format"] == "json":
            return cls.from_json_file(file_path, update)
        else:
            raise Exception("unknown file format")

    @classmethod
    def from_yaml_file(cls, file_path: Path, update: bool) -> "FrequencyList":
        """
        Read file with frequency in the format:
        `<word>: <number of occurrences>`.

        :param file_path: input YAML file name.
        :param update: whether source file is constantly updated.
        """
        try:
            return cls.from_list_file(file_path, ": ", update)
        except Exception:
            frequency_list = cls(update)

            structure = yaml.load(open(file_path), Loader=yaml.FullLoader)

            for word in structure:
                frequency_list.data[word] = structure[word]

        frequency_list.sort()

        return frequency_list

    @classmethod
    def from_json_file(cls, file_path: Path, update: bool) -> "FrequencyList":
        """
        Read file with frequency in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param file_path: input JSON file name.
        :param update: whether source file is constantly updated.
        """
        with file_path.open() as input_file:
            structure: list[(str, int)] = json.load(input_file)

        frequency_list = cls(update)

        for word, occurrences in structure:
            word: str
            occurrences: int
            frequency_list.data[word] = int(occurrences)
            frequency_list.occurrences += occurrences

        frequency_list.sort()

        return frequency_list

    @classmethod
    def from_csv_file(
        cls,
        file_path: Path,
        header: list[str],
        delimiter: str = ",",
        update: bool = False,
    ) -> "FrequencyList":
        frequency_list: "FrequencyList" = cls(update)

        count_index = header.index("count")
        word_index = header.index("word")

        with file_path.open() as input_file:
            for line in input_file.readlines()[1:]:
                parts = line.split(delimiter)
                frequency_list.add(parts[word_index], int(parts[count_index]))

        return frequency_list

    @classmethod
    def from_list_file(
        cls, file_path: Path, delimiter: str = " ", update: bool = False
    ) -> "FrequencyList":
        """
        Read file with frequency in the format:
        `<word><delimiter><number of occurrences>`.

        :param file_path: input text file name.
        :param delimiter: delimiter between word and its number of occurrences.
        :param update: whether source file is constantly updated.
        """
        lines: list[str] = file_path.open().readlines()
        lines_number: int = len(lines)
        length: int = len(delimiter)

        frequency_list = cls(update)

        for index, line in enumerate(lines):
            index: int
            line: str
            progress_bar(index, lines_number)
            try:
                position: int = line.find(delimiter)
                word: str = line[:position]
                occurrences: int = int(line[position + length :])
            except ValueError:
                raise MalformedFile(file_path)
            frequency_list.data[word] = occurrences
            frequency_list.occurrences += occurrences

        progress_bar(-1, 0)

        frequency_list.sort()

        return frequency_list

    @classmethod
    def from_word_list_file(
        cls, file_path: Path, update: bool
    ) -> "FrequencyList":

        frequency_list: "FrequencyList" = cls(update)
        with file_path.open() as input_file:
            for line in input_file.readlines():
                frequency_list.add(line[:-1])

        return frequency_list

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

    def write_json(self, output_path: Path) -> None:
        """
        Write frequency list in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param output_path: path to output JSON file.
        """
        structure: list = []
        for word in sorted(self.data.keys(), key=lambda x: -self.data[x]):
            word: str
            structure.append([word, self.data[word]])
        with output_path.open("w+") as output_file:
            json.dump(structure, output_file, indent=4, ensure_ascii=False)

    def add(self, word: str, occurrences: int = 1) -> None:
        """Add word and its occurrences in some text."""
        if word not in self.data:
            self.data[word] = 0

        self.data[word] += occurrences
        self.occurrences += occurrences
        self.sorted_keys = None

    def ignore_proper_nouns(self) -> None:
        """Make frequency list case-insensitive."""
        for word in self.data.keys():
            word: str
            if word.lower() != word:
                if word.lower() in self.data:
                    self.data[word.lower()] += self.data[word]
                del self.data[word]
        self.sort()

    def has(self, word: str) -> bool:
        """Check whether frequency list contains word."""
        return word in self.data

    def get_occurrences(self, word: str) -> int:
        """Get number of word occurrences in text."""
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
        """Get number of all words in the text."""
        return self.occurrences

    def get_words(self) -> list[str]:
        """Get all unique words."""
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
        """Get word of the specified index."""
        word: str = self.sorted_keys[index]
        return word, self.data[word]

    def sort(self) -> None:
        """Sort keys by frequency."""
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

    def get_index(self, word: str):
        if word in self.sorted_keys:
            return self.sorted_keys.index(word)
        else:
            return -1


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
                (index, word, occurrences),
            )
        self.connection.commit()
