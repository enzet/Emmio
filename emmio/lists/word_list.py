import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Self, override

from emmio.lists.config import WordListConfig
from emmio.lists.core import List


@dataclass
class WordList(List):
    """Word list."""

    file_path: Path
    """Path to the word list file."""

    config: WordListConfig
    """Configuration for the word list."""

    data: list[str]
    """List of words, the order is arbitrary."""

    @classmethod
    def from_config(cls, path: Path, config: WordListConfig) -> Self:
        """Load a word list from a config."""

        file_path: Path = path / config.path
        logging.debug("Loading word list from list file `%s`.", file_path)

        with file_path.open(encoding="utf-8") as input_file:
            data = [x[:-1] for x in input_file.readlines()]

        return cls(file_path, config, data)

    @override
    def get_name(self) -> str:
        return self.config.name

    @override
    def get_info(self) -> str:
        return (
            f"  Length: {len(self.data)}\n"
            f"  Language: {self.config.language}"
        )

    @override
    def get_words(self) -> list[str]:
        return self.data
