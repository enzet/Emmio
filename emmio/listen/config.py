"""Configuration for listening."""

from pathlib import Path

from pydantic import BaseModel

from emmio.language import LanguageConfig


class ListenConfig(BaseModel):
    """Configuration for listening."""

    file_name: Path
    """Path to the file with listening data."""

    base_language: LanguageConfig
    """Language known by the user used for translations."""

    learning_id: str
    """Identifier of the learning process."""

    lists: list[dict[str, str]]
    """Configurations of words or frequency lists.

    They will be used to pick up new words for listening.
    """

    audio_base: list[dict[str, str]]
    """Audio files for words in base language."""

    audio_learning: list[dict[str, str]]
    """Audio files for words in learning language."""

    dictionaries: list[dict[str, str]]
    """Configurations of dictionaries to use."""
