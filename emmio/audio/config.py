from pydantic.main import BaseModel

from emmio.language import LanguageConfig


class AudioConfig(BaseModel):
    directory_name: str
    """
    Directory with audio files (probably structured with more directory levels).
    """

    format: str
    """Audio file extension."""

    language: LanguageConfig
    """Language of the files."""
