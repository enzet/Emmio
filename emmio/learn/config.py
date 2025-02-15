from enum import Enum

from pydantic import BaseModel

from emmio.language import LanguageConfig


# TODO: This should be deleted and replaced with more carefully created learning
#       scheme configuration.
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
    """How to pick new question."""

    pick_from: list[dict]
    """Which question lists use to pick new question."""

    check_lexicons: list[dict] | None = None
    """Which lexicon to check to skip already known questions."""

    ask_lexicon: dict | None = None
    """Which lexicon to ask to pick new question."""

    ignore_not_common: list[dict] | None = None
    """Which words to ignore."""


class Scheme(BaseModel):
    """Learning scheme.

    This configuration describes how to pick new questions, how to show them,
    how to postpone them, and what actions to perform after showing them.
    """

    new_question: NewQuestionScheme | None = None
    """How to pick new question."""

    show_question: list[dict] | None = None
    """How to show question."""

    postpone_time: float | None = None
    """How long to postpone question, relative to the last request time."""

    actions: list[dict] = []
    """Actions to perform after question is shown."""

    learning_lexicon: dict | None = None
    """Which lexicon should be used to store answers during learning."""


class LearnConfig(BaseModel):
    """Learning process configuration."""

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

    sentences: list[dict] | None = None
    """Sentences usage configurations."""

    dictionaries: list[dict]
    """Dictionary usage configurations."""

    audio: list[dict] = []
    """Configurations for voice-over."""

    check_lexicon: bool = False
    ask_lexicon: bool = False
    max_for_day: int = 10
