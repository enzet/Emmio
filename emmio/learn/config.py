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


class NewQuestionScheme(BaseModel):
    pick_from: list[dict]
    """Which question lists use to pick new question."""

    check_lexicons: list[dict] | None = None
    """Which lexicon to check to skip already known questions."""

    ask_lexicon: dict | None = None
    ignore_not_common: list[dict]


class Scheme(BaseModel):
    new_question: NewQuestionScheme | None = None
    show_question: list[dict] | None = None
    postpone_time: float | None = None

    learning_lexicon: dict | None = None
    """Which lexicon should be used to store answers during learning."""


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

    scheme: Scheme | None
    """Learning scheme."""

    sentences: list[dict]
    """Sentences usage configurations."""

    dictionaries: list[dict]
    """Dictionary usage configurations."""

    audio: list[dict] = []
    """Configurations for voice-over."""

    check_lexicon: bool = False
    ask_lexicon: bool = False
    max_for_day: int = 10
