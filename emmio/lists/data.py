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

    def get_frequency_list_options(self) -> list[dict]:
        """List every frequency list available, across all languages.

        Two sources are covered: configured `frequency_list` entries
        (preferred) and the FrequencyWords (OpenSubtitles) lists, which are
        plain files named `<language>_opensubtitles_<year>.txt` in the
        directory rather than entries in the configuration. Unlike
        `get_frequency_list_languages`, every option is kept — e.g. every
        cached FrequencyWords year — so a picker can offer a choice; for a
        given language, the first option in the returned list is the one
        `get_frequency_list_languages` would pick automatically.

        :return: list of `{"language", "name", "config"}`, where `config` is
            a `ListUsageConfig`-shaped dict ready to store as a lexicon's or
            course's `pick_from` entry
        """
        options: list[dict] = []
        languages_seen: set[str] = set()

        # Configured frequency lists take priority, one option per id.
        for id_, config in self.list_configs.items():
            if (
                isinstance(config, dict)
                and config.get("type") == "frequency_list"
                and (language := config.get("language")) is not None
            ):
                options.append(
                    {
                        "language": language,
                        "name": config.get("name") or id_,
                        "config": {"id": id_},
                    }
                )
                languages_seen.add(language)

        # FrequencyWords lists are files, not configuration entries; a
        # language may have more than one cached year, newest first.
        downloaded_years: dict[str, list[int]] = {}
        for file_path in self.path.glob("*_opensubtitles_*.txt"):
            match = re.fullmatch(
                r"(?P<language>.+)_opensubtitles_(?P<year>\d+)", file_path.stem
            )
            if match is None:
                continue
            downloaded_years.setdefault(match["language"], []).append(
                int(match["year"])
            )
        for language, years in downloaded_years.items():
            options.extend(
                {
                    "language": language,
                    "name": f"FrequencyWords ({year})",
                    "config": {
                        "id": "frequency_words",
                        "language": language,
                        "year": year,
                    },
                }
                for year in sorted(years, reverse=True)
            )
            languages_seen.add(language)

        # Languages with nothing downloaded or configured yet: offer the best
        # release, fetched in the background on first use.
        for language, year in FREQUENCY_WORDS_YEARS.items():
            if language in languages_seen:
                continue
            options.append(
                {
                    "language": language,
                    "name": f"FrequencyWords ({year})",
                    "config": {
                        "id": "frequency_words",
                        "language": language,
                        "year": year,
                    },
                }
            )

        return options

    def get_frequency_list_languages(self) -> dict[str, dict]:
        """Map each language with a frequency list to its default usage config.

        The default is the first (highest-priority) option
        `get_frequency_list_options` returns for the language — see there for
        the precedence order.

        :return: mapping from language code (e.g. `uk`) to a frequency-list
            usage config (the `ListUsageConfig` fields) ready to store on a
            lexicon
        """
        languages: dict[str, dict] = {}
        for option in self.get_frequency_list_options():
            languages.setdefault(option["language"], option["config"])
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
