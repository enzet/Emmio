"""Configuration of a dictionary."""

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class DictionaryUsageConfig(BaseModel):
    """Configuration of a dictionary."""

    id: str
    """Identifier of the dictionary."""

    from_language: LanguageConfig | None = None
    """Language of words being defined."""

    to_language: LanguageConfig | None = None
    """Language of definitions and translations."""

    name: str | None = None
    """Additional name to identify the dictionary."""


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

    is_machine: bool = False
    """Whether translations or definitions are machine-generated."""
