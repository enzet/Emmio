from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


class LearnType(Enum):
    SENTENCES = "sentences"
    """
    In this learning scheme the teacher process provides a translation of the
    word being studied from a dictionary and a number of sentences in the target
    language
    """


class LearnConfig(BaseModel):
    file_name: str
    """Name of the file with learning process."""

    name: str
    """Name of the learning course."""

    learning_language: LanguageConfig
    """Learning subject."""

    base_language: LanguageConfig
    """Language known by user."""

    is_active: bool = True
    """Whether the learning process is active now."""

    type: LearnType
    """Learning scheme."""

    sentences: list[dict]
    dictionaries: list[dict]
    lists: list[str]

    audio: list[dict] = {}
    """Configurations for voice-over."""

    check_lexicon: bool = False
    ask_lexicon: bool = False
    max_for_day: int = 10
