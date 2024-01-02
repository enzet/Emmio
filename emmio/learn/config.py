from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


class LearnScheme(Enum):
    """Learning scheme."""

    SENTENCES = "sentences"
    """
    In this learning scheme the teacher process provides a clues for the word
    being studied:
      - a definition of the word from a defining dictionary in the learning
        language and/or a translation of the word in one of the base languages,
      - a sentence in the learning language with the word being hided,
      - translations of the sentence in one of the base languages.
    """

    FULL_SENTENCES = "full_sentences"


class LearnConfig(BaseModel):
    file_name: str
    """Name of the file with learning process."""

    name: str
    """Name of the learning course."""

    learning_language: LanguageConfig
    """Learning subject."""

    base_languages: list[LanguageConfig]
    """Languages known by user."""

    is_active: bool = True
    """Whether the learning process is active now."""

    type: LearnScheme
    """Learning scheme."""

    sentences: list[dict]
    """Sentences usage configurations."""

    dictionaries: list[dict]
    lists: list[str]

    audio: list[dict] = {}
    """Configurations for voice-over."""

    check_lexicon: bool = False
    ask_lexicon: bool = False
    max_for_day: int = 10
