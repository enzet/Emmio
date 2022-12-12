from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from emmio.language import LanguageConfig


class FrequencyListFileFormat(Enum):
    """File format of the frequency list."""

    LIST = "list"
    """File with lines `word occurrences`."""

    JSON = "json"
    """File with format [[word, occurrences]]."""


class FrequencyListConfig(BaseModel):
    """Configuration of the word list or frequency list."""

    name: str
    source: str
    file_format: FrequencyListFileFormat
    language: LanguageConfig
    path: Path
    url: str | None

    is_stripped: bool
    """False for a full frequency list for some text or corpus."""


class WordListConfig(BaseModel):
    """Configuration of the word list or frequency list."""

    name: str
    source: str
    language: LanguageConfig
    path: Path
