"""Configuration of a dictionary."""

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class DictionaryConfig(BaseModel):
    """Configuration of a dictionary."""

    file_name: str
    """Name of the file with dictionary."""

    name: str
    """Dictionary name."""

    from_language: LanguageConfig
    """Language of words being defined."""

    to_language: LanguageConfig
    """Language of definitions and translations."""
