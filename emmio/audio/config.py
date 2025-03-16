"""Configuration for audio files."""

from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class AudioConfig(BaseModel):
    """Configuration for a collection of audio files."""

    directory_name: str
    """Directory with audio files.

    It may be structured with more directory levels.
    """

    format: str
    """Audio file extension, e.g. `ogg` or `wav`."""

    language: LanguageConfig
    """Language of the files."""
