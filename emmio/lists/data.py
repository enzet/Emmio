"""Data for lists."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.catalog import FREQUENCY_WORDS_YEARS
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
from emmio.util import log_duration

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class ListsData(ArtifactData):
    """Manages directory with frequency lists and word lists."""

    path: Path
    """The directory managed by this class."""

    list_configs: dict[str, Any]
    """Raw per-list configuration, loaded lazily on first request."""

    frequency_lists: dict[str, FrequencyList]
    """Cache of frequency lists already loaded."""

    word_lists: dict[str, WordList]
    """Cache of word lists already loaded."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize lists from a directory.

        Lists are loaded lazily (on first request), not here: loading every
        configured list eagerly takes seconds and most are never used.

        :param path: path to the directory with lists
        """
        return cls(path, ArtifactData.read_config(path), {}, {})

    def get_frequency_list(
        self, list_usage_config: ListUsageConfig
    ) -> FrequencyList | None:
        """Get frequency list."""

        match id_ := list_usage_config.id:
            case "frequency_words":
                if list_usage_config.language is None:
                    msg = "Language is required for FrequencyWords list."
                    raise ValueError(msg)
                if list_usage_config.year is None:
                    msg = "Year is required for FrequencyWords list."
                    raise ValueError(msg)
                # Cache the loaded list: it is large (~1M words, seconds to
                # load) and requested on every word-selection request.
                cache_key: str = (
                    f"frequency_words:{list_usage_config.language}:"
                    f"{list_usage_config.year}"
                )
                if cache_key not in self.frequency_lists:
                    with log_duration(
                        f"load frequency list {list_usage_config.language}/"
                        f"{list_usage_config.year}",
                        logger,
                    ):
                        self.frequency_lists[cache_key] = (
                            FrequencyWordsList.from_short_config(
                                self.path,
                                Language.from_code(list_usage_config.language),
                                list_usage_config.year,
                            )
                        )
                return self.frequency_lists[cache_key]
            case _:
                if id_ in self.frequency_lists:
                    return self.frequency_lists[id_]
                list_config = self.list_configs.get(id_)
                if (
                    not list_config
                    or list_config.get("type") != "frequency_list"
                ):
                    return None
                with log_duration(f"load frequency list `{id_}`", logger):
                    self.frequency_lists[id_] = FrequencyList.from_config(
                        self.path, FrequencyListConfig(**list_config)
                    )
                return self.frequency_lists[id_]

    def get_frequency_list_languages(self) -> dict[str, dict]:
        """Map each language with a frequency list to its usage config.

        Two sources are covered: configured `frequency_list` entries (preferred)
        and the FrequencyWords (Opensubtitles) lists, which are plain files
        named `<language>_opensubtitles_<year>.txt` in the directory rather than
        entries in the configuration. For the latter the most recent year wins.

        :return: mapping from language code (e.g. `uk`) to a frequency-list
            usage config (the `ListUsageConfig` fields) ready to store on a
            lexicon
        """
        languages: dict[str, dict] = {}

        # Configured frequency lists take priority.
        for id_, config in self.list_configs.items():
            if (
                isinstance(config, dict)
                and config.get("type") == "frequency_list"
                and (language := config.get("language")) is not None
            ):
                languages.setdefault(language, {"id": id_})

        # FrequencyWords lists are files, not configuration entries; keep the
        # most recent year for each language.
        best_year: dict[str, int] = {}
        for file_path in self.path.glob("*_opensubtitles_*.txt"):
            match = re.fullmatch(
                r"(?P<language>.+)_opensubtitles_(?P<year>\d+)", file_path.stem
            )
            if match is None:
                continue
            language = match["language"]
            year: int = int(match["year"])
            if year > best_year.get(language, 0):
                best_year[language] = year
        for language, year in best_year.items():
            languages.setdefault(
                language,
                {"id": "frequency_words", "language": language, "year": year},
            )

        # Languages whose FrequencyWords list is not downloaded yet but can be:
        # offer them too (the file is fetched on first use). Downloaded and
        # configured lists above still win.
        for language, year in FREQUENCY_WORDS_YEARS.items():
            languages.setdefault(
                language,
                {"id": "frequency_words", "language": language, "year": year},
            )

        return languages

    def get_list(self, list_usage_config: ListUsageConfig) -> List | None:
        """Get word list or frequency list."""

        if frequency_list := self.get_frequency_list(list_usage_config):
            return frequency_list

        id_: str = list_usage_config.id
        if id_ in self.word_lists:
            return self.word_lists[id_]
        list_config = self.list_configs.get(id_)
        if list_config and list_config.get("type") == "word_list":
            with log_duration(f"load word list `{id_}`", logger):
                self.word_lists[id_] = WordList.from_config(
                    self.path, WordListConfig(**list_config)
                )
            return self.word_lists[id_]
        return None
