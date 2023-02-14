import logging
from dataclasses import dataclass
from pathlib import Path

from emmio.lists.config import WordListConfig
from emmio.lists.core import List


@dataclass
class WordList(List):
    file_path: Path
    config: WordListConfig
    data: list[str] | None = None

    @classmethod
    def from_config(cls, path: Path, config: WordListConfig):
        return cls(path / config.path, config)

    def load(self) -> None:
        if self.data:
            return
        if self.file_path.exists():
            self.load_from_file()
        else:
            raise Exception(f"No file {self.config.path}")

    def load_from_file(self) -> None:
        logging.debug(f"Loading word list from list file {self.file_path}.")

        with self.file_path.open() as input_file:
            self.data = [x[:-1] for x in input_file.readlines()]

    def get_name(self) -> str:
        return self.config.name

    def get_info(self) -> str:
        return (
            f"  Length: {len(self.data)}\n"
            f"  Language: {self.config.language}"
        )

    def get_words(self) -> list[str]:
        self.load()
        return self.data
