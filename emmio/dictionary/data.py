"""Data for dictionaries."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from emmio.catalog import KAIKKI_LANGUAGES
from emmio.core import ArtifactData
from emmio.dictionary.config import DictionaryConfig, DictionaryUsageConfig
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    SimpleDictionary,
    StructuredDictionary,
)
from emmio.dictionary.en_wiktionary import (
    DictionaryDownloadError,
    EnglishWiktionaryKaikki,
    kaikki_language_name,
)
from emmio.dictionary.google_translate import GoogleTranslate
from emmio.language import Language

logger: logging.Logger = logging.getLogger(__name__)


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

    # `threading.Lock` is a factory, not a type beartype can check, so `Any`.
    _kaikki_downloads_lock: Any = field(
        default_factory=threading.Lock, repr=False
    )
    """Guards `_kaikki_downloading` across the request threadpool."""

    _kaikki_downloading: set[str] = field(default_factory=set, repr=False)
    """English names of languages whose Kaikki cache is being built now.

    A Kaikki dictionary is a large (hundreds of MB) download, so it is fetched
    in the background rather than inside the request; this set deduplicates the
    background jobs while one is in flight.
    """

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize dictionaries from a directory.

        :param path: path to the directory with dictionaries
        """
        config: dict[str, Any] = ArtifactData.read_config(path)

        dictionaries: dict[str, Dictionary] = {}
        for id_, data in config.items():
            dictionary_config = DictionaryConfig(**data)
            builder = (
                StructuredDictionary
                if dictionary_config.type == "structured"
                else SimpleDictionary
            )
            dictionaries[id_] = builder.from_config(
                path, id_, dictionary_config
            )
        return cls(path, dictionaries)

    def has_kaikki(self, language: Language) -> bool:
        """Check whether a Kaikki (en.wiktionary) dictionary exists for it.

        Kaikki caches are stored under `cache/kaikki/<kaikki.org name>`, so its
        presence tells whether the language can be looked up at all.
        """
        name: str = kaikki_language_name(language)
        return (self.path / "cache" / "kaikki" / name).is_dir()

    @staticmethod
    def can_download_kaikki(language: Language) -> bool:
        """Whether kaikki.org has an English-Wiktionary dictionary for it.

        Based on the static `KAIKKI_LANGUAGES` catalog, so a lexicon can attach
        Kaikki before it is downloaded (it is fetched in the background on first
        use).
        """
        return language.get_code() in KAIKKI_LANGUAGES

    def _start_kaikki_download(self, language: Language, name: str) -> None:
        """Fetch and build a Kaikki cache in the background, at most once.

        The Kaikki words file is hundreds of megabytes, so downloading it inside
        a request would block it for minutes; instead a daemon thread builds the
        cache while the lexicon keeps working through its other dictionaries.
        The cache is picked up automatically once ready.
        """
        with self._kaikki_downloads_lock:
            if name in self._kaikki_downloading or self.has_kaikki(language):
                return
            self._kaikki_downloading.add(name)

        def download() -> None:
            try:
                EnglishWiktionaryKaikki(
                    self.path, self.path / "cache", language, name
                )
                logger.info("Kaikki dictionary for `%s` is ready.", name)
            except (DictionaryDownloadError, ValueError):
                logger.exception("Failed to download `%s` Kaikki.", name)
            finally:
                with self._kaikki_downloads_lock:
                    self._kaikki_downloading.discard(name)

        threading.Thread(target=download, daemon=True).start()

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
                language: Language = Language.from_code(
                    dictionary_usage_config.from_language
                )
                # Not downloaded yet: fetch it in the background (it is huge),
                # letting the lexicon fall back to its other dictionaries now.
                if not self.has_kaikki(language):
                    self._start_kaikki_download(
                        language, dictionary_usage_config.name
                    )
                    return None
                cache_key: tuple[str, str] = (
                    dictionary_usage_config.from_language,
                    dictionary_usage_config.name,
                )
                if cache_key not in self._kaikki_cache:
                    self._kaikki_cache[cache_key] = EnglishWiktionaryKaikki(
                        self.path,
                        self.path / "cache",
                        language,
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
