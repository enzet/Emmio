import json
from dataclasses import dataclass
from pathlib import Path

from emmio.dictionary.config import DictionaryConfig
from emmio.dictionary.core import Dictionary, Dictionaries, SimpleDictionary
from emmio.dictionary.en_wiktionary import EnglishWiktionary
from emmio.language import construct_language


@dataclass
class DictionaryData:
    """Manager for the directory with dictionaries."""

    path: Path
    """The directory managed by this class."""

    dictionaries: dict[str, Dictionary]

    @classmethod
    def from_config(cls, path: Path) -> "DictionaryData":
        with (path / "config.json").open() as config_file:
            config: dict = json.load(config_file)
        dictionaries: dict[str, Dictionary] = {}
        for id_, data in config.items():
            dictionaries[id_] = SimpleDictionary.from_config(
                path, DictionaryConfig(**data)
            )
        return cls(path, dictionaries)

    def get_dictionary(self, dictionary_usage_config: dict) -> Dictionary:

        match id_ := dictionary_usage_config["id"]:
            case "en_wiktionary":
                return EnglishWiktionary(
                    self.path / "cache",
                    construct_language(dictionary_usage_config["language"]),
                )
            case _:
                return self.dictionaries[id_]

    def get_dictionaries(
        self, dictionary_usage_configs: list[dict]
    ) -> Dictionaries:
        return Dictionaries(
            [self.get_dictionary(x) for x in dictionary_usage_configs]
        )
