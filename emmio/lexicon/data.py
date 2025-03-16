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
        lexicons: dict[str, Lexicon] = {}

        for lexicon_id, lexicon_config in config.items():
            try:
                lexicons[lexicon_id] = Lexicon(
                    path, LexiconConfig(**lexicon_config)
                )
            except ValidationError as e:
                logging.fatal(
                    f"Error loading lexicon `{lexicon_id}` with config "
                    f"`{lexicon_config}`: {e}."
                )
                sys.exit(1)

        return cls(path, lexicons)

    def get_lexicons(
        self, languages: list[Language] | None = None
    ) -> list[Lexicon]:
        if languages:
            result = []
            for lexicon in self.lexicons.values():
                if lexicon.language in languages:
                    result.append(lexicon)
            return result
        else:
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
        return self.lexicons[lexicon_id]

    def get_frequency_lexicons(self) -> dict[Language, list[Lexicon]]:
        result: dict[Language, list[Lexicon]] = defaultdict(list)
        for lexicon in self.lexicons.values():
            if lexicon.is_frequency():
                result[lexicon.language].append(lexicon)
        return result
