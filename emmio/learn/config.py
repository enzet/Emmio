from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


class LearnType(Enum):
    SENTENCES = "sentences"


class LearnConfig(BaseModel):

    path: str
    """Name of the file with learning process."""

    name: str
    """Name of the learning course."""

    learning_language: LanguageConfig
    """Learning subject."""

    base_language: LanguageConfig
    """Language known by user."""

    is_active: bool = True
    type: LearnType
    sentences: list[dict]
    dictionaries: list[dict]
    lists: list[str]
    check_lexicon: bool = False
    ask_lexicon: bool = False
