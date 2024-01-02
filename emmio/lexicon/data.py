from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio.language import Language
from emmio.lexicon.config import LexiconConfig
from emmio.lexicon.core import Lexicon


@dataclass
class LexiconData:
    """Manages directory with lexicons."""

    path: Path
    """The directory managed by this class."""

    lexicons: dict[str, Lexicon]
    """Mapping from lexicon identifier to lexicon."""

    @classmethod
    def from_config(cls, path: Path, config: dict) -> "LexiconData":
        lexicons: dict[str, Lexicon] = {}

        for lexicon_id, lexicon_config in config.items():
            lexicons[lexicon_id] = Lexicon(
                path, LexiconConfig(**lexicon_config)
            )

        return cls(path, lexicons)

    def get_lexicons(self) -> Iterator[Lexicon]:
        return iter(self.lexicons.values())

    def get_lexicon(self, language: Language) -> Lexicon | None:
        """Get lexicon with the requested language."""

        lexicons: list[Lexicon] = [
            x for x in self.lexicons.values() if x.language == language
        ]
        if len(lexicons) == 1:
            return lexicons[0]

        return None
