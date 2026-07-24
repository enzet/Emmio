"""Configuration of a dictionary."""

from typing import Literal

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

    type: Literal["file", "structured"] = "file"
    """Storage format.

    `file` is a flat word-to-definition-string map (`SimpleDictionary`), the
    long-standing default. `structured` holds full dictionary items —
    multiple forms, per-language definitions, transcriptions, and links
    (`StructuredDictionary`) — for entries a single string cannot express,
    e.g. an alphabet letter's name in several languages plus its case or
    positional variants.
    """

    file_name: str
    """Name of the file with dictionary."""

    name: str
    """Dictionary name."""

    from_language: LanguageConfig
    """Language of words being defined."""

    to_language: LanguageConfig | None = None
    """Language of definitions and translations.

    Required for `file` (every entry shares one target language); unused for
    `structured`, whose definitions are already keyed per language.
    """

    is_machine: bool = False
    """Whether translations or definitions are machine-generated."""
