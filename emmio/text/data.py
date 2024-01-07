import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from emmio.text.config import TextConfig, TextTranslationConfig
from emmio.text.core import Texts


@dataclass
class TextData:
    """Manages data inside texts directory."""

    path: Path
    texts: dict[str, Texts]

    @classmethod
    def from_config(cls, path: Path) -> "TextData":
        config: dict

        if not path.exists():
            if path.parent.exists():
                path.mkdir()
                config = {}
            else:
                logging.fatal(f"{path.parent} doesn't exist.")
                raise FileNotFoundError()
        else:
            with (path / "config.json").open() as config_file:
                config = json.load(config_file)

        texts: dict[str, Texts] = {}

        for text_id, text_config in config.items():
            texts[text_id] = Texts.from_config(
                path, TextTranslationConfig(**text_config)
            )

        return cls(path, texts)

    def get_text(self, text_id) -> Texts:
        return self.texts[text_id]
