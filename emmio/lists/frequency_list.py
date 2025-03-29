"""Frequency list."""

import json
import logging
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self, override

import urllib3

from emmio.language import Language
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.core import List


class WordOccurrences:
    """Unique word and number of its occurrences in some text."""

    word: str
    """Unique word."""

    occurrences: int
    """Number of occurrences of the word in some text."""


@dataclass
class FrequencyList(List):
    """Frequency list of some text.

    It is a list of all unique words in the text and the number of their
    occurrences.
    """

    file_path: Path
    """Path to the file with the frequency list."""

    config: FrequencyListConfig
    """Configuration of the frequency list."""

    data: dict[str, int]
    """Mapping from words to their number of occurrences."""

    _occurrences: int = 0
    """Total number of occurrences of all words in the frequency list."""

    _sorted_keys: list[str] = field(default_factory=list)
    """List of words sorted by their number of occurrences."""

    @classmethod
    def from_config(cls, path: Path, config: FrequencyListConfig) -> Self:
        """Load frequency list from file or URL.

        :param path: path to the directory with lists
        :param config: configuration of the frequency list
        """

        file_path: Path = path / config.path

        if file_path.exists():
            return cls.from_file(path, config, file_path)
        if config.url:
            return cls.from_url(path, config, config.url)
        raise ValueError(f"Unable to load frequency list {config}.")

    def __post_init__(self) -> None:
        if self.data:
            self._occurrences: int = sum(self.data.values())
            self._sorted_keys: list[str] = sorted(
                self.data.keys(), key=lambda word: -self.data[word]
            )

        assert self._occurrences == sum(self.data.values()), (
            f"Precomputed number of occurrences {self._occurrences} is not "
            f"equal to the sum of occurrences: {sum(self.data.values())}."
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
            self.data.keys(), key=lambda word: -self.data[word]
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
            self.data.keys(), key=lambda word: -self.data[word]
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
        """Get word index in frequency list.

        The most popular word in the text has index 1. If word is not in
        frequency list, return -1.
        """
        if word in self._sorted_keys:
            return self._sorted_keys.index(word)
        return -1

    def get_all_occurrences(self) -> int:
        """Get number of all words in the text."""
        return self._occurrences

    def get_words(self) -> list[str]:
        """Get all unique words."""
        return self._sorted_keys

    def get_random_word(self) -> tuple[str, int]:
        """Return random unique word regardless of its frequency.

        :return: word, number of its occurrences in text
        """
        word: str = random.choice(list(self.data.keys()))
        return word, self.data[word]

    def get_word_by_occurrences(self, occurrences: int) -> tuple[str, int]:
        """Get first word with occurrences more or equals to specified number.

        :return: word and its number of occurrences in the text
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
        """Return random word based on its frequency.

        This function is equivalent to picking up random word from the text,
        which was used to create this frequency list in the first place.

        :return: (word, number of its occurrences in text)
        """
        number: int = random.randint(0, self._occurrences)

        index: int = 0
        for word in self._sorted_keys:
            index += self.data[word]
            if index >= number:
                return word, self.data[word]

        raise OverflowError(
            "Unable to get word from a frequency list. Total occurrences "
            f"number is {self._occurrences}. Number is {number}. Last index "
            "is {index}."
        )

    def get_index(self, word: str) -> int:
        """Get index of the word in the frequency list.

        :return: index of the word in the frequency list or -1 if the word is
            not in the frequency list
        """
        if word in self._sorted_keys:
            return self._sorted_keys.index(word)
        return -1

    @override
    def get_name(self) -> str | None:
        """Get name of the list."""
        return self.config.name

    def get_info(self) -> str:
        """Get information about the list."""
        return f"  Length: {len(self)}\n" f"  Language: {self.config.language}"

    @classmethod
    def from_file(
        cls, path: Path, config: FrequencyListConfig, file_path: Path
    ) -> Self:
        """Load frequency list from file."""

        match config.file_format:
            case FrequencyListFileFormat.JSON:
                return cls.from_json_file(path, config, file_path)
            case FrequencyListFileFormat.LIST:
                return cls.from_list_file(path, config, file_path)
            case FrequencyListFileFormat.CSV:
                return cls.from_csv_file(path, config, file_path)
            case _:
                raise ValueError(f"unknown file format `{config.file_format}`")

    @classmethod
    def from_csv_file(
        cls, path: Path, config: FrequencyListConfig, file_path: Path
    ) -> Self:
        """Load frequency list from CSV file."""

        logging.debug("Loading frequency list from CSV file `%s`.", file_path)

        data: dict[str, int] = {}
        occurrences: int = 0
        sorted_keys: list[str] = []

        count_index: int = config.csv_header.index("count")
        word_index: int = config.csv_header.index("word")

        with file_path.open(encoding="utf-8") as input_file:
            for line in input_file.readlines()[1:]:
                parts = line.split(config.csv_delimiter)
                count: int = int(parts[count_index])
                word: str = parts[word_index]
                if word in data:
                    # This can happen when frequency list considers different
                    # forms as different words.
                    data[word] += count
                else:
                    data[word] = count
                occurrences += count
                sorted_keys.append(word)

        return cls(path, config, data, occurrences, sorted_keys)

    @classmethod
    def from_json_file(
        cls, path: Path, config: FrequencyListConfig, file_path: Path
    ) -> Self:
        """Load frequency list from JSON file."""

        logging.debug("Loading frequency list from JSON file `%s`.", file_path)
        with file_path.open(encoding="utf-8") as input_file:
            structure: list[tuple[str, int]] = json.load(input_file)

        return cls(path, config, dict(structure))

    @classmethod
    def from_list_file(
        cls, path: Path, config: FrequencyListConfig, file_path: Path
    ) -> Self:
        """Load frequency list from list file."""

        logging.debug("Loading frequency list from list file `%s`.", file_path)
        data: dict[str, int] = {}

        with file_path.open(encoding="utf-8") as input_file:
            while line := input_file.readline():
                try:
                    position: int = line.find(" ")
                    word: str = line[:position]
                    occurrences: int = int(line[position + 1 :])
                    data[word] = occurrences
                except ValueError:
                    pass

        return cls(path, config, data)

    @classmethod
    def from_url(
        cls, path: Path, config: FrequencyListConfig, url: str
    ) -> Self:
        """Load frequency list from URL."""

        logging.info("Loading frequency list from url `%s`...", url)

        pool_manager: urllib3.PoolManager = urllib3.PoolManager()
        response: urllib3.BaseHTTPResponse = pool_manager.request(
            "GET", url, preload_content=False
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

        file_path: Path = path / config.path

        with file_path.open("bw+") as cache_file:
            cache_file.write(data)

        return cls.from_file(path, config, file_path)


class FrequencyWordsList(FrequencyList):
    """Frequency list from FrequencyWords project.

    FrequencyWords is a project that contains frequency lists extracted from
    Opensubtitles.

    See https://github.com/hermitdave/FrequencyWords
    """

    @classmethod
    def from_short_config(
        cls, path: Path, language: Language, year: int
    ) -> Self:
        """Create frequency list from language and year.

        :param path: path to the directory with lists
        :param language: language of the frequency list
        :param year: year of the frequency list
        """
        return cls.from_config(
            path,
            FrequencyListConfig(
                name=f"{language.get_name()} Opensubtitles {year}",
                source="FrequencyWords by Hermit Dave",
                path=f"{language.get_code()}_opensubtitles_{year}.txt",
                file_format=FrequencyListFileFormat.LIST,
                language=language.get_code(),
                is_stripped=False,
                url=(
                    "https://raw.githubusercontent.com/hermitdave/"
                    f"FrequencyWords/master/content/{year}/"
                    f"{language.get_code()}/{language.get_code()}_full.txt"
                ),
            ),
        )
