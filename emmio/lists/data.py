from dataclasses import dataclass
from pathlib import Path

from emmio.core import ArtifactData
from emmio.language import Language
from emmio.lists.config import FrequencyListConfig, WordListConfig
from emmio.lists.core import List
from emmio.lists.frequency_list import FrequencyList, FrequencyWordsList
from emmio.lists.word_list import WordList


@dataclass
class ListsData(ArtifactData):
    """Manages directory with frequency lists and word lists."""

    path: Path
    """The directory managed by this class."""

    frequency_lists: dict[str, FrequencyList]
    word_lists: dict[str, List]

    @classmethod
    def from_config(cls, path: Path) -> "ListsData":
        """Initialize lists from a directory."""
        config: dict = ArtifactData.read_config(path)

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

    def get_frequency_list(
        self, list_usage_config: dict
    ) -> FrequencyList | None:
        """Get frequency list."""

        match id_ := list_usage_config["id"]:
            case "frequency_words":
                frequency_list: FrequencyWordsList = FrequencyWordsList(
                    self.path,
                    Language.from_code(list_usage_config["language"]),
                    list_usage_config["year"],
                )
                frequency_list.load()
                return frequency_list
            case _:
                if id_ not in self.frequency_lists:
                    return None

                self.frequency_lists[id_].load()

                return self.frequency_lists[id_]

    def get_list(self, list_usage_config: dict) -> List | None:
        """Get word list or frequency list."""

        if frequency_list := self.get_frequency_list(list_usage_config):
            return frequency_list

        if list_usage_config["id"] in self.word_lists:
            return self.word_lists[list_usage_config["id"]]

        return None
