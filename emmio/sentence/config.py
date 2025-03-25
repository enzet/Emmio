"""Configuration of sentences."""

from pydantic import BaseModel

from emmio.language import LanguageConfig


class SentencesUsageConfig(BaseModel):
    """Configuration of sentences."""

    id: str
    """Identifier of the sentences."""

    languages: tuple[LanguageConfig, LanguageConfig] | None = None
    """Languages of the sentences."""


class SentenceConfig(BaseModel):
    """Configuration of sentences."""

    file_name: str
    """Name of the file with sentences."""

    name: str
    """Name of the sentences."""

    language_1: LanguageConfig
    """Language of sentences."""

    language_2: LanguageConfig
    """Language of translations."""
