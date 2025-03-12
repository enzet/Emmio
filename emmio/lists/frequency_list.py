import json
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import urllib3

from emmio.language import Language
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.core import List, ListCollection


class WordOccurrences:
    """Unique word and number of its occurrences in some text."""

    word: str
    """Unique word."""

    occurrences: int
    """Number of occurrences of the word in some text."""


@dataclass
class FrequencyList(List):
    """Frequency list of some text."""

    file_path: Path
    config: FrequencyListConfig
    data: dict[str, int] | None = None
    _occurrences: int = 0
    _sorted_keys: list[str] = field(default_factory=list)

    @classmethod
    def from_config(cls, path: Path, config: FrequencyListConfig):
        return cls(path / config.path, config)

    def __post_init__(self):
        if self.data:
            self._occurrences: int = sum(self.data.values())
            self._sorted_keys: list[str] = sorted(
                self.data.keys(), key=lambda x: -self.data[x]
            )

    def __len__(self) -> int:
        return len(self.data)

    def add(self, word: str, occurrences: int = 1) -> None:
        """Add word and its occurrences in some text."""
        if not self.data:
            self.data = {}
        if word not in self.data:
            self.data[word] = 0
        self.data[word] += occurrences
        self._occurrences += occurrences
        self._sorted_keys = sorted(
            self.data.keys(), key=lambda x: -self.data[x]
        )

    def ignore_proper_nouns(self) -> None:
        """Make frequency list case-insensitive."""
        keys: list[str] = list(self.data.keys())
        for word in keys:
            if word.lower() != word:
                if word.lower() in self.data:
                    self.data[word.lower()] += self.data[word]
                del self.data[word]
        self._sorted_keys = sorted(
            self.data.keys(), key=lambda x: -self.data[x]
        )

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
        if word in self._sorted_keys:
            return self._sorted_keys.index(word)
        return -1

    def get_all_occurrences(self) -> int:
        """Get number of all words in the text."""
        return self._occurrences

    def get_words(self) -> list[str]:
        """Get all unique words."""
        self.load()
        return self._sorted_keys

    def get_random_word(self) -> tuple[str, int]:
        """
        Return random unique word regardless of its frequency.

        :return word, number of its occurrences in text
        """
        word: str = random.choice(list(self.data.keys()))
        return word, self.data[word]

    def get_word_by_occurrences(self, occurrences: int) -> tuple[str, int]:
        """
        Get first word with the number of occurrences more or equals to
        specified number.

        :return word and its number of occurrences in the text
        """
        for word in self._sorted_keys:
            if self.data[word] >= occurrences:
                return word, self.data[word]

        return "", 0

    def get_word_by_index(self, index: int) -> tuple[str, int]:
        """Get word of the specified index."""
        word: str = self._sorted_keys[index]
        return word, self.data[word]

    def get_random_word_by_frequency(self) -> tuple[str, int]:
        """
        Return random word based on its frequency as if you pick up random word
        from the text.

        :return word, number of its occurrences in text
        """
        if self._occurrences == 0:
            self.load()

        number: int = random.randint(0, self._occurrences)

        index: int = 0
        for word in self._sorted_keys:
            index += self.data[word]
            if index >= number:
                return word, self.data[word]

        raise Exception(
            "Unable to get word from a frequency list. Total occurrences "
            f"number is {self._occurrences}. Number is {number}. Last index "
            "is {index}."
        )

    def get_index(self, word: str) -> int:
        """Get index of the word in the frequency list.

        :return index of the word in the frequency list or -1 if the word is
            not in the frequency list
        """
        if word in self._sorted_keys:
            return self._sorted_keys.index(word)
        return -1

    def get_name(self) -> str | None:
        """Get name of the list."""
        return self.config.name

    def get_info(self) -> str:
        """Get information about the list."""
        return f"  Length: {len(self)}\n" f"  Language: {self.config.language}"

    def load(self) -> None:
        """Load data if necessary."""
        if self.data:
            return

        if self.file_path.exists():
            self.load_from_file()
        elif self.config.url:
            self.load_from_url()
        else:
            raise Exception(f"Unable to load frequency list {self.config}.")

        assert self._occurrences == sum(self.data.values()), (
            f"Precomputed number of occurences {self._occurrences} is not "
            f"equal to the sum of occurences: {sum(self.data.values())}."
        )

    def load_from_file(self) -> None:
        match self.config.file_format:
            case FrequencyListFileFormat.JSON:
                self.load_from_json_file()
            case FrequencyListFileFormat.LIST:
                self.load_from_list_file()
            case FrequencyListFileFormat.CSV:
                self.load_from_csv_file(
                    self.config.csv_delimiter, self.config.csv_header
                )
            case _:
                raise Exception(
                    f"unknown file format {self.config.file_format}"
                )

    def load_from_csv_file(self, delimiter: str, header: list[str]) -> None:
        logging.debug(f"Loading frequency list from CSV file {self.file_path}.")

        self.data = {}
        self._occurrences = 0
        self._sorted_keys = []

        count_index: int = header.index("count")
        word_index: int = header.index("word")

        with self.file_path.open() as input_file:
            for line in input_file.readlines()[1:]:
                parts = line.split(delimiter)
                count: int = int(parts[count_index])
                word: str = parts[word_index]
                if word in self.data:
                    # This can happen when frequency list considers different
                    # forms as different words.
                    self.data[word] += count
                else:
                    self.data[word] = count
                self._occurrences += count
                self._sorted_keys.append(word)

    def load_from_json_file(self) -> None:
        logging.debug(
            f"Loading frequency list from JSON file {self.file_path}."
        )
        with self.file_path.open() as input_file:
            structure: list[(str, int)] = json.load(input_file)

        self.data = {word: occurrences for word, occurrences in structure}
        self.__post_init__()

    def load_from_list_file(self) -> None:
        logging.debug(
            f"Loading frequency list from list file {self.file_path}."
        )
        self.data = {}

        with self.file_path.open() as input_file:
            while line := input_file.readline():
                try:
                    position: int = line.find(" ")
                    word: str = line[:position]
                    occurrences: int = int(line[position + 1 :])
                    self.data[word] = occurrences
                except ValueError:
                    pass
        self.__post_init__()

    def load_from_url(self) -> None:
        logging.info(f"Loading frequency list from url `{self.config.url}`...")

        pool_manager: urllib3.PoolManager = urllib3.PoolManager()
        response: urllib3.HTTPResponse = pool_manager.request(
            "GET", self.config.url, preload_content=False
        )
        pool_manager.clear()
        data: bytearray = bytearray()
        sys.stdout.write("Downloading: ")
        while True:
            buffer = response.read(400_000)
            sys.stdout.write("█")
            sys.stdout.flush()
            if not buffer:
                break
            data.extend(buffer)
        sys.stdout.write("\n")

        with self.file_path.open("bw+") as cache_file:
            cache_file.write(data)

        self.load_from_file()


class FrequencyWordsList(FrequencyList):
    """Frequency list from project FrequencyWords.

    FrequencyWords is a project that contains frequency lists extracted from
    Opensubtitles.

    See https://github.com/hermitdave/FrequencyWords
    """

    def __init__(self, path: Path, language: Language, year: int):
        super().__init__(
            path / f"{language.get_code()}_opensubtitles_{year}.txt",
            FrequencyListConfig(
                name=f"{language.get_name()} Opensubtitles {year}",
                source="FrequencyWords by Hermit Dave",
                path=f"{language.get_code()}_opensubtitles_{year}.txt",
                file_format="list",
                language=language.get_code(),
                is_stripped=False,
                url=(
                    "https://raw.githubusercontent.com/hermitdave/"
                    f"FrequencyWords/master/content/{year}/"
                    f"{language.get_code()}/{language.get_code()}_full.txt"
                ),
            ),
        )


@dataclass
class FrequencyListCollection(ListCollection):
    def get_words_by_turn(self, minimum_frequency: int = 0) -> Iterator[str]:
        index: int = 0
        for frequency_list in self.collection:
            if len(frequency_list) > index:
                yield frequency_list.get_words()[index]
            index += 1
