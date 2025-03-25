"""Data for lists."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.core import ArtifactData
from emmio.language import Language
from emmio.lists.config import (
    FrequencyListConfig,
    ListUsageConfig,
    WordListConfig,
)
from emmio.lists.core import List
from emmio.lists.frequency_list import FrequencyList, FrequencyWordsList
from emmio.lists.word_list import WordList


@dataclass
class ListsData(ArtifactData):
    """Manages directory with frequency lists and word lists."""

    path: Path
    """The directory managed by this class."""

    frequency_lists: dict[str, FrequencyList]
    """Collection of frequency lists."""

    word_lists: dict[str, WordList]
    """Collection of word lists."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize lists from a directory.

        :param path: path to the directory with lists
        """
        config: dict[str, Any] = ArtifactData.read_config(path)

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
                    raise ValueError(
                        "Unknown list configuration type "
                        f"`{list_config['type']}`."
                    )

        return cls(path, frequency_lists, word_lists)

    def get_frequency_list(
        self, list_usage_config: ListUsageConfig
    ) -> FrequencyList | None:
        """Get frequency list."""

        match id_ := list_usage_config.id:
            case "frequency_words":
                if list_usage_config.language is None:
                    raise ValueError(
                        "Language is required for FrequencyWords list."
                    )
                if list_usage_config.year is None:
                    raise ValueError(
                        "Year is required for FrequencyWords list."
                    )
                frequency_list: FrequencyWordsList = (
                    FrequencyWordsList.from_short_config(
                        self.path,
                        Language.from_code(list_usage_config.language),
                        list_usage_config.year,
                    )
                )
                return frequency_list
            case _:
                if id_ not in self.frequency_lists:
                    return None

                return self.frequency_lists[id_]

    def get_list(self, list_usage_config: ListUsageConfig) -> List | None:
        """Get word list or frequency list."""

        if frequency_list := self.get_frequency_list(list_usage_config):
            return frequency_list

        if list_usage_config.id in self.word_lists:
            return self.word_lists[list_usage_config.id]

        return None
