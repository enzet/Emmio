"""Configuration for listening."""

from pathlib import Path

from pydantic import BaseModel

from emmio.audio.config import AudioUsageConfig
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import LanguageConfig
from emmio.lists.config import ListUsageConfig

ListenConfigValuesType = str | list[dict[str, str]]
ListenConfigType = dict[str, ListenConfigValuesType]


class ListenConfig(BaseModel):
    """Configuration for listening."""

    file_name: Path
    """Path to the file with listening data."""

    base_language: LanguageConfig
    """Language known by the user used for translations."""

    learning_id: str
    """Identifier of the learning process."""

    lists: list[ListUsageConfig]
    """Configurations of words or frequency lists.

    They will be used to pick up new words for listening.
    """

    audio_base: list[AudioUsageConfig]
    """Audio files for words in base language."""

    audio_learning: list[AudioUsageConfig]
    """Audio files for words in learning language."""

    dictionaries: list[DictionaryUsageConfig]
    """Configurations of dictionaries to use."""
