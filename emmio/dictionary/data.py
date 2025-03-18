"""Data for dictionaries."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio.core import ArtifactData
from emmio.dictionary.config import DictionaryConfig
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    SimpleDictionary,
)
from emmio.dictionary.en_wiktionary import EnglishWiktionaryKaikki
from emmio.dictionary.google_translate import GoogleTranslate
from emmio.language import Language


@dataclass
class DictionaryData(ArtifactData):
    """Manager for the directory with dictionaries."""

    path: Path
    """The directory managed by this class."""

    dictionaries: dict[str, Dictionary]
    """Mapping from unique dictionary string identifier to dictionary."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize dictionaries from a directory.

        :param path: path to the directory with dictionaries
        """
        config: dict = ArtifactData.read_config(path)

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
            case "kaikki":
                return EnglishWiktionaryKaikki(
                    self.path,
                    self.path / "cache",
                    Language.from_code(dictionary_usage_config["language"]),
                    dictionary_usage_config["name"],
                )
            case "google_translate":
                return GoogleTranslate(
                    self.path,
                    self.path / "cache",
                    Language.from_code(dictionary_usage_config["from"]),
                    Language.from_code(dictionary_usage_config["to"]),
                )
            case _:
                if id_ in self.dictionaries:
                    return self.dictionaries[id_]

        return None

    def get_dictionaries(
        self, dictionary_usage_configs: list[dict]
    ) -> DictionaryCollection:
        """Get dictionaries by dictionary usage configurations.

        :param dictionary_usage_configs: list of dictionary usage configurations
        :return: collection of dictionaries
        """
        dictionaries: list[Dictionary] = []
        for dictionary_usage_config in dictionary_usage_configs:
            dictionary: Dictionary | None = self.get_dictionary(
                dictionary_usage_config
            )
            if dictionary:
                dictionaries.append(dictionary)
        return DictionaryCollection(dictionaries)

    def get_dictionaries_by_language(
        self, from_language: Language, to_language: Language
    ) -> DictionaryCollection:
        """Get dictionaries by languages.

        :param from_language: language of requests
        :param to_language: language of definitions
        :return: collection of dictionaries
        """

        def check(dictionary: Dictionary) -> bool:
            return dictionary.check_from_language(
                from_language
            ) and dictionary.check_to_language(to_language)

        return DictionaryCollection(
            [x for x in self.dictionaries.values() if check(x)]
        )
