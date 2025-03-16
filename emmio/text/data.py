"""Data for texts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio.core import ArtifactData
from emmio.text.config import TextTranslationConfig
from emmio.text.core import Texts


@dataclass
class TextData(ArtifactData):
    """Manages data inside texts directory."""

    path: Path
    """Path to the directory containing the texts."""

    texts: dict[str, Texts]
    """Mapping of text identifiers to texts."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Read texts from a configuration file.

        :param path: path to the directory with texts
        """
        config: dict = ArtifactData.read_config(path)

        texts: dict[str, Texts] = {}

        for text_id, text_config in config.items():
            texts[text_id] = Texts.from_config(
                path, TextTranslationConfig(**text_config)
            )

        return cls(path, texts)

    def get_text(self, text_id: str) -> Texts:
        """Get a text by its identifier."""
        return self.texts[text_id]
