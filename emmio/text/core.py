"""Core functionality for texts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio.language import Language
from emmio.text.config import TextTranslationConfig


@dataclass
class Texts:
    """Text in some language and its translations."""

    data: dict[Language, list[str]]
    """Mapping of languages to lists of sentences in these languages."""

    @classmethod
    def from_config(cls, path: Path, config: TextTranslationConfig) -> Self:
        """Read texts from a configuration file.

        :param path: path to the directory with texts
        :param config: configuration for texts
        """
        data: dict[Language, list[str]] = {}
        for text_config in config.texts:
            language: Language = Language.from_code(text_config.language)
            with (path / text_config.file_path).open(
                encoding="utf-8"
            ) as input_file:
                lines: list[str] = input_file.readlines()
            data[language] = [x[:-1] for x in lines]

        return cls(data)
