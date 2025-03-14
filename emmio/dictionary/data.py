from dataclasses import dataclass
from pathlib import Path

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
    def from_config(cls, path: Path) -> "DictionaryData":
        """Initialize dictionaries from a directory."""
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
        dictionaries: list[Dictionary] = []
        for dictionary_usage_config in dictionary_usage_configs:
            dictionary: Dictionary | None = self.get_dictionary(
                dictionary_usage_config
            )
            if dictionary:
                dictionaries.append(dictionary)
        return DictionaryCollection(dictionaries)

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
