"""Configuration for the lexicon."""

from enum import StrEnum

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


class LexiconSelection(StrEnum):
    """How words for lexicon checking was picked.

    A `StrEnum`, so members compare and hash equal to their stored string
    values: configurations read from the database or JSON can be checked
    against members directly, and members serialize as plain strings.
    """

    RANDOM = "random"
    """Words were picked uniformly at random from the frequency list."""

    ARBITRARY = "arbitrary"
    """Words were picked arbitrarily.

    Used for lexicons imported from elsewhere, where the selection procedure is
    external and not reproducible here. Such lexicons have no check method.
    """

    FREQUENCY = "frequency"
    """Frequency-weighted random sampling (FWR).

    Words were drawn with probability proportional to their corpus frequency.
    """

    LOGISTIC = "logistic"
    """Logistic model with adaptive sampling (LA).

    Words were picked to maximally reduce the variance of the estimate under a
    fitted logistic model.
    """

    THRESHOLD = "threshold"
    """Optimal frequency threshold (OT)."""

    STRATIFIED = "stratified"
    """Stratified frequency-weighted random sampling (SFWR)."""

    TOP = "top"
    """Select the first unanswered word from the frequency list (by rank)."""

    UNKNOWN = "unknown"
    """Selection is unknown."""


class LexiconConfig(BaseModel):
    """Configuration for the lexicon."""

    language: LanguageConfig
    """Language of the lexicon."""

    selection: LexiconSelection
    """How words was picked."""

    name: str | None = None
    """Human-readable display name; the identifier is used when not set."""

    frequency_list: ListUsageConfig | None = None
    """Frequency list used to check lexicon."""

    dictionaries: list[DictionaryUsageConfig] | None = None
    """Dictionary usage configurations."""

    sentences: list[SentencesUsageConfig] | None = None
    """Sentences configurations."""
