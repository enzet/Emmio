"""Frequency list utility."""
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from sqlite3 import Cursor
from typing import Any, Optional

import urllib3
import yaml
from urllib3 import HTTPResponse

from emmio.database import Database
from emmio.language import construct_language
from emmio.util import MalformedFile

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class WordOccurrences:
    """Unique word and number of its occurrences in some text."""

    word: str
    occurrences: int


@dataclass
class FrequencyList:
    """Frequency list of some text."""

    data: dict[str, int] = field(default_factory=dict)
    occurrences: int = 0
    sorted_keys: list[str] = field(default_factory=list)
    update: bool = False

    def __len__(self) -> int:
        return len(self.data)

    @classmethod
    def from_structure(
        cls, structure: dict[str, Any], directory: Path
    ) -> Optional["FrequencyList"]:
        """
        Construct frequency list from description.

        :param structure: dictionary with frequency list description
        :param directory: directory to store frequency lists
        """
        frequency_list: "FrequencyList" = cls(
            structure["id"],
            construct_language(structure["language"]),
            structure["is_full"],
            structure["update"],
        )

        temp_path: Path = directory / f'{structure["id"]}.tmp'
        if temp_path.exists():
            (frequency_list := cls.from_file(temp_path, structure)).write_json(
                cache_path
            )
            return frequency_list

        if "path" in structure:
            frequency_list.parse_file(Path(structure["path"]), structure)
            return frequency_list

        if "url" in structure:
            pool_manager: urllib3.PoolManager = urllib3.PoolManager()
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

    def parse_file(self, file_path: Path, structure: dict[str, Any]) -> None:
        """
        Read frequency list from the file.

        :param file_path: input file name.
        :param structure: structure describing file format.
        """
        if structure["format"] == "yaml":
            return self.parse_yaml(file_path)
        elif structure["format"] == "list":
            return self.parse_list(file_path, structure["delimiter"])
        elif structure["format"] == "word_list":
            return self.parse_word_list(file_path)
        elif structure["format"] == "csv":
            return self.parse_csv(
                file_path, structure["header"], structure["delimiter"]
            )
        elif structure["format"] == "json":
            return self.parse_json(file_path)
        else:
            raise Exception("unknown file format")

    def parse_yaml(self, file_path: Path) -> None:
        """
        Read file with frequency in the format:
        `<word>: <number of occurrences>`.

        :param file_path: input YAML file name.
        :param update: whether source file is constantly updated.
        """
        try:
            self.parse_list(file_path, ": ")
        except Exception:
            for word, occurrences in yaml.load(
                open(file_path), Loader=yaml.FullLoader
            ).items():
                self.data[word] = occurrences

    def parse_json(self, file_path: Path) -> None:
        """
        Read file with frequency in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param file_path: input JSON file name.
        """
        with file_path.open() as input_file:
            structure: list[(str, int)] = json.load(input_file)

        for word, occurrences in structure:
            word: str
            occurrences: int
            self.data[word] = int(occurrences)
            self.occurrences += occurrences

    def parse_csv(
        self, file_path: Path, header: list[str], delimiter: str = ","
    ) -> None:
        count_index = header.index("count")
        word_index = header.index("word")

        with file_path.open() as input_file:
            for line in input_file.readlines()[1:]:
                parts = line.split(delimiter)
                self.add(parts[word_index], int(parts[count_index]))

    def parse_list(self, file_path: Path, delimiter: str = " ") -> None:
        """
        Read file with frequency in the format:
        `<word><delimiter><number of occurrences>`.

        :param file_path: input text file name.
        :param delimiter: delimiter between word and its number of occurrences.
        """
        length: int = len(delimiter)

        for index, line in enumerate(file_path.open().readlines()):
            index: int
            line: str
            try:
                position: int = line.find(delimiter)
                word: str = line[:position]
                occurrences: int = int(line[position + length :])
            except ValueError:
                raise MalformedFile(file_path)
            self.data[word] = occurrences
            self.occurrences += occurrences

    def parse_word_list(self, file_path: Path) -> None:
        with file_path.open() as input_file:
            for line in input_file.readlines():
                self.add(line[:-1])

    def write_list(self, output_path: Path, delimiter: str = " ") -> None:
        """
        Write frequency list in the format:
        `<word><delimiter><number of occurrences>`.

        :param output_path: output text file path.
        :param delimiter: delimiter between word and its number of occurrences.
        """
        with output_path.open("w+") as output_file:
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
