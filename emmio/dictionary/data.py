"""Data for dictionaries."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from emmio.core import ArtifactData
from emmio.dictionary.config import DictionaryConfig, DictionaryUsageConfig
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

    _kaikki_cache: dict[tuple[str, str], EnglishWiktionaryKaikki] = field(
        default_factory=dict
    )
    """Cache of constructed Kaikki dictionaries, keyed by language and name.

    Kaikki dictionaries parse a whole shard file on first lookup of a word and
    keep parsed items in memory, so reusing the same instance across requests
    avoids re-reading multi-megabyte shards on every translation.
    """

    _google_translate_cache: dict[tuple[str, str], GoogleTranslate] = field(
        default_factory=dict
    )
    """Cache of Google Translate dictionaries, keyed by language pair.

    Reusing the same instance keeps a single HTTP client alive across requests
    (connection keepalive) and an in-memory cache of looked-up words, so
    uncached translations avoid a fresh TLS handshake on every request.
    """

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize dictionaries from a directory.

        :param path: path to the directory with dictionaries
        """
        config: dict[str, Any] = ArtifactData.read_config(path)

        dictionaries: dict[str, Dictionary] = {}
        for id_, data in config.items():
            dictionaries[id_] = SimpleDictionary.from_config(
                path, id_, DictionaryConfig(**data)
            )
        return cls(path, dictionaries)

    def has_kaikki(self, language: Language) -> bool:
        """Check whether a Kaikki (en.wiktionary) dictionary exists for it.

        Kaikki caches are stored under `cache/kaikki/<English language name>`,
        so its presence tells whether the language can be looked up at all.
        """
        return (self.path / "cache" / "kaikki" / language.get_name()).is_dir()

    def get_dictionary(
        self, dictionary_usage_config: DictionaryUsageConfig
    ) -> Dictionary | None:
        """Get dictionary by dictionary usage configuration."""

        match id_ := dictionary_usage_config.id:
            case "kaikki":
                if dictionary_usage_config.from_language is None:
                    msg = "`from_language` is required for Kaikki dictionary."
                    raise ValueError(msg)
                if dictionary_usage_config.name is None:
                    msg = "Name is required for Kaikki dictionary."
                    raise ValueError(msg)
                cache_key: tuple[str, str] = (
                    dictionary_usage_config.from_language,
                    dictionary_usage_config.name,
                )
                if cache_key not in self._kaikki_cache:
                    self._kaikki_cache[cache_key] = EnglishWiktionaryKaikki(
                        self.path,
                        self.path / "cache",
                        Language.from_code(
                            dictionary_usage_config.from_language
                        ),
                        dictionary_usage_config.name,
                    )
                return self._kaikki_cache[cache_key]
            case "google_translate":
                if dictionary_usage_config.from_language is None:
                    msg = (
                        "`from_language` is required for Google Translate "
                        "dictionary."
                    )
                    raise ValueError(msg)
                if dictionary_usage_config.to_language is None:
                    msg = (
                        "`to_language` is required for Google Translate "
                        "dictionary."
                    )
                    raise ValueError(msg)
                google_key: tuple[str, str] = (
                    dictionary_usage_config.from_language,
                    dictionary_usage_config.to_language,
                )
                if google_key not in self._google_translate_cache:
                    self._google_translate_cache[google_key] = GoogleTranslate(
                        self.path,
                        self.path / "cache",
                        Language.from_code(
                            dictionary_usage_config.from_language
                        ),
                        Language.from_code(dictionary_usage_config.to_language),
                    )
                return self._google_translate_cache[google_key]
            case _:
                if id_ in self.dictionaries:
                    return self.dictionaries[id_]
                msg = f"Unknown dictionary: `{id_}`."
                raise ValueError(msg)

        return None

    def get_dictionaries(
        self, dictionary_usage_configs: list[DictionaryUsageConfig]
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
