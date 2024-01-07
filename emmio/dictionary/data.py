import json
import logging
from dataclasses import dataclass
from pathlib import Path

from emmio.dictionary.config import DictionaryConfig
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    SimpleDictionary,
)
from emmio.dictionary.en_wiktionary import EnglishWiktionary
from emmio.language import construct_language, Language


@dataclass
class DictionaryData:
    """Manager for the directory with dictionaries."""

    path: Path
    """The directory managed by this class."""

    dictionaries: dict[str, Dictionary]
    """Mapping from unique dictionary string identifier to dictionary."""

    @classmethod
    def from_config(cls, path: Path) -> "DictionaryData":
        """Initialize dictionaries from a directory."""
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

        dictionaries: dict[str, Dictionary] = {}
        for id_, data in config.items():
            dictionaries[id_] = SimpleDictionary.from_config(
                path, id_, DictionaryConfig(**data)
            )
        return cls(path, dictionaries)

    def get_dictionary(
        self, dictionary_usage_config: dict
    ) -> Dictionary | None:
        """Get dictionary by dictionary usage configuration."""
        match id_ := dictionary_usage_config["id"]:
            case "en_wiktionary":
                return EnglishWiktionary(
                    self.path / "cache",
                    construct_language(dictionary_usage_config["language"]),
                )
            case _:
                if id_ in self.dictionaries:
                    return self.dictionaries[id_]

        return None

    def get_dictionaries(
        self, dictionary_usage_configs: list[dict]
    ) -> DictionaryCollection:
        return DictionaryCollection(
            [self.get_dictionary(x) for x in dictionary_usage_configs]
        )

    def get_dictionaries_by_language(
        self, language_1: Language, language_2: Language
    ) -> DictionaryCollection:
        def check(dictionary) -> bool:
            return dictionary.check_from_language(
                language_1
            ) and dictionary.check_from_language(language_2)

        return DictionaryCollection(
            [x for x in self.dictionaries.values() if check(x)]
        )
