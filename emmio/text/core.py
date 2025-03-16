"""Core functionality for texts."""

from dataclasses import dataclass
from pathlib import Path

from emmio.language import Language, construct_language
from emmio.text.config import TextTranslationConfig


@dataclass
class Texts:
    """Text in some language and its translations."""

    data: dict[Language, list[str]]
    """Mapping of languages to lists of sentences in these languages."""

    @classmethod
    def from_config(cls, path: Path, config: TextTranslationConfig) -> "Texts":
        """Read texts from a configuration file."""

        data: dict[Language, list[str]] = {}
        for text_config in config.texts:
            language: Language = construct_language(text_config.language)
            with (path / text_config.file_path).open() as input_file:
                lines: list[str] = input_file.readlines()
            data[language] = [x[:-1] for x in lines]

        return cls(data)
