from pydantic import BaseModel

from emmio.language import LanguageConfig


class TextConfig(BaseModel):
    """Configuration for a text."""

    file_path: str
    """Path to the text file with the text."""

    language: LanguageConfig
    """Language of the text."""


class TextTranslationConfig(BaseModel):
    """Configuration for a collection of texts."""

    texts: list[TextConfig]
    """Text and it's translations to other languages."""

    original_language: LanguageConfig | None = None
    """The language of the original text (optional)."""
