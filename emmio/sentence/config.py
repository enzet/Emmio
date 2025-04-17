"""Configuration of sentences."""

from enum import Enum
from pydantic import BaseModel

from emmio.language import LanguageConfig


class SentenceType(Enum):
    """Type of the sentences."""

    SIMPLE_ONE_LANGUAGE = "simple_one_language"
    """Simple sentences with one language."""

    SIMPLE_TWO_LANGUAGES = "simple_two_languages"
    """Simple sentences with two languages."""


class SentencesUsageConfig(BaseModel):
    """Configuration of sentences."""

    id: str
    """Identifier of the sentences."""

    language: LanguageConfig
    """Language of the sentences."""

    translation_languages: list[LanguageConfig] | None = None
    """Languages of translations."""


class SentenceConfig(BaseModel):
    """Configuration of sentences."""

    file_name: str
    """Name of the file with sentences."""

    type: SentenceType
    """Type of the sentences."""

    name: str
    """Name of the sentences."""

    languages: list[LanguageConfig]
    """Languages of sentences."""
