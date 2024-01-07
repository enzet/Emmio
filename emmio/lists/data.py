import json
import logging
from dataclasses import dataclass
from pathlib import Path

from emmio.lists.config import FrequencyListConfig, WordListConfig
from emmio.lists.core import List
from emmio.lists.frequency_list import FrequencyList
from emmio.lists.word_list import WordList


@dataclass
class ListsData:
    """Manages directory with frequency lists and word lists."""

    path: Path
    """The directory managed by this class."""

    frequency_lists: dict[str, FrequencyList]
    word_lists: dict[str, List]

    @classmethod
    def from_config(cls, path: Path) -> "ListsData":
        """Initialize lists from a directory."""
        config: dict

        if not path.exists():
            if path.parent.exists():
                path.mkdir()
                config = {}
            else:
                logging.fatal(f"{path.parent} doesn't exist.")
                raise FileNotFoundError()
        else:
            with (path / "config.json").open() as config_file:
                config = json.load(config_file)

        frequency_lists: dict[str, FrequencyList] = {}
        word_lists: dict[str, WordList] = {}

        for list_id, list_config in config.items():
            match list_config["type"]:
                case "frequency_list":
                    frequency_lists[list_id] = FrequencyList.from_config(
                        path, FrequencyListConfig(**list_config)
                    )
                case "word_list":
                    word_lists[list_id] = WordList.from_config(
                        path, WordListConfig(**list_config)
                    )
                case _:
                    raise Exception(
                        f"unknown list configuration type {list_config['type']}"
                    )

        return cls(path, frequency_lists, word_lists)

    def get_frequency_list(self, id_: str) -> FrequencyList | None:
        """Get frequency list."""

        if id_ not in self.frequency_lists:
            return None

        self.frequency_lists[id_].load()

        return self.frequency_lists[id_]

    def get_list(self, id_: str) -> List | None:
        if id_ in self.frequency_lists:
            return self.frequency_lists[id_]
        if id_ in self.word_lists:
            return self.word_lists[id_]
        return None
