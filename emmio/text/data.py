from dataclasses import dataclass
from pathlib import Path

from emmio.core import ArtifactData
from emmio.text.config import TextTranslationConfig
from emmio.text.core import Texts


@dataclass
class TextData(ArtifactData):
    """Manages data inside texts directory."""

    path: Path
    texts: dict[str, Texts]

    @classmethod
    def from_config(cls, path: Path) -> "TextData":
        config: dict = ArtifactData.read_config(path)

        texts: dict[str, Texts] = {}

        for text_id, text_config in config.items():
            texts[text_id] = Texts.from_config(
                path, TextTranslationConfig(**text_config)
            )

        return cls(path, texts)

    def get_text(self, text_id) -> Texts:
        return self.texts[text_id]
