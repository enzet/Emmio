"""Configuration for the lexicon."""

from enum import Enum

from pydantic.main import BaseModel

from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import LanguageConfig
from emmio.lists.config import ListUsageConfig
from emmio.sentence.config import SentencesUsageConfig

LexiconConfigValuesType = (
    str | int | dict[str, str] | list[dict[str, str]] | None
)
LexiconConfigType = dict[str, LexiconConfigValuesType]


class LexiconUsageConfig(BaseModel):
    """Configuration of the lexicon."""

    id: str
    """Identifier of the lexicon."""


class LexiconSelection(Enum):
    """How words for lexicon checking was picked."""

    BINARY_SEARCH = "binary_search"
    """Words were picked from binary search."""

    RANDOM = "random"
    """Words were picked randomly."""

    ARBITRARY = "arbitrary"
    """Words were picked arbitrarily."""

    FREQUENCY = "frequency"
    """Words were picked from the specified frequency list."""

    UNKNOWN = "unknown"
    """Selection is unknown."""


class LexiconConfig(BaseModel):
    """Configuration for the lexicon."""

    file_name: str
    """Path to the lexicon JSON file."""

    language: LanguageConfig
    """Language of the lexicon."""

    selection: LexiconSelection
    """How words was picked."""

    frequency_list: ListUsageConfig | None = None
    """Frequency list used to check lexicon."""

    dictionaries: list[DictionaryUsageConfig] = []
    """Dictionary usage configurations."""

    sentences: list[SentencesUsageConfig] = []
    """Sentences configurations."""

    precision_per_week: int = 0
    """Needed precision for every week.

    When rechecking the lexicon, the process will stop, when the needed
    precision will be achieved.
    """
