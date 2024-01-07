from pydantic import BaseModel

from emmio.language import LanguageConfig


class ReadConfig(BaseModel):
    """Configuration of text reading process."""

    file_name: str
    """File to store reading history."""

    from_language: LanguageConfig
    """Language of the text."""

    to_language: LanguageConfig
    """Language of the translation."""

    text: str
    """Text unique identifier."""

    dictionaries: list[dict]
    """Dictionaries to translate unknown words."""
