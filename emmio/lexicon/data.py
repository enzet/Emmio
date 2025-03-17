"""Lexicon data."""

import logging
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from pydantic import ValidationError

from emmio.language import Language
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import Lexicon


@dataclass
class LexiconData:
    """Manages directory with lexicons."""

    path: Path
    """The directory managed by this class."""

    lexicons: dict[str, Lexicon] = field(default_factory=dict)
    """Mapping from lexicon identifier to lexicon."""

    @classmethod
    def from_config(cls, path: Path, config: dict) -> Self:
        """Create a new lexicon data instance from a configuration.

        :param path: path to the directory with lexicons
        :param config: configuration
        """
        lexicons: dict[str, Lexicon] = {}

        for lexicon_id, lexicon_config in config.items():
            try:
                lexicons[lexicon_id] = Lexicon(
                    path, LexiconConfig(**lexicon_config)
                )
            except ValidationError as e:
                logging.fatal(
                    "Error loading lexicon `%s` with config `%s`: %s.",
                    lexicon_id,
                    lexicon_config,
                    e,
                )
                sys.exit(1)

        return cls(path, lexicons)

    def get_lexicons(
        self, languages: list[Language] | None = None
    ) -> list[Lexicon]:
        """Get lexicons for the specified languages.

        :param languages: languages to get lexicons for
        """
        if languages:
            result = []
            for lexicon in self.lexicons.values():
                if lexicon.language in languages:
                    result.append(lexicon)
            return result

        return list(self.lexicons.values())

    def get_lexicons_by_language(self, language: Language) -> list[Lexicon]:
        """Get lexicons with the requested language."""
        return [x for x in self.lexicons.values() if x.language == language]

    def get_frequency_lexicons_by_language(
        self, language: Language
    ) -> list[Lexicon]:
        """Get lexicons with the requested language."""
        return [
            x
            for x in self.lexicons.values()
            if x.language == language and x.is_frequency()
        ]

    def get_lexicon_by_id(self, lexicon_id: str) -> Lexicon:
        """Get a lexicon by its identifier.

        :param lexicon_id: identifier of the lexicon
        """
        return self.lexicons[lexicon_id]

    def get_frequency_lexicons(self) -> dict[Language, list[Lexicon]]:
        """Get all lexicons based on frequency lists."""

        result: dict[Language, list[Lexicon]] = defaultdict(list)
        for lexicon in self.lexicons.values():
            if lexicon.is_frequency():
                result[lexicon.language].append(lexicon)
        return result
