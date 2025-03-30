"""Learning configuration."""

from enum import Enum

from pydantic import BaseModel

from emmio.audio.config import AudioUsageConfig
from emmio.dictionary.config import DictionaryUsageConfig
from emmio.language import LanguageConfig
from emmio.lexicon.config import LexiconUsageConfig
from emmio.lists.config import ListUsageConfig
from emmio.sentence.config import SentencesUsageConfig

LearningConfigValuesType = (
    str
    | list[str]
    | list[dict[str, str]]
    | dict[str, dict[str, list[dict[str, str]]]]
)
LearningConfigType = dict[str, LearningConfigValuesType]


class NewQuestionScheme(BaseModel):
    """How to pick new question."""

    pick_from: list[ListUsageConfig]
    """Which question lists use to pick new question."""

    check_lexicons: list[LexiconUsageConfig] | None = None
    """Which lexicon to check to skip already known questions."""

    ask_lexicon: LexiconUsageConfig | None = None
    """Which lexicon to ask to pick new question."""

    ignore_not_common: list[DictionaryUsageConfig] | None = None
    """Dictionaries for checking if the word is common."""


class ActionType(str, Enum):
    """Type of the action."""

    SHOW_QUESTION_ID = "show_question_id"
    """Just show question ID."""

    CHECK_TRANSLATION = "check_translation"
    """Check translation."""


class Action(BaseModel):
    """Action to perform after question is shown."""

    type: ActionType
    """Type of the action."""


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

    actions: list[Action] = []
    """Actions to perform after question is shown."""

    learning_lexicon: LexiconUsageConfig | None = None
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

    sentences: list[SentencesUsageConfig] | None = None
    """Sentences usage configurations."""

    dictionaries: list[DictionaryUsageConfig]
    """Dictionary usage configurations."""

    audio: list[AudioUsageConfig] = []
    """Configurations for audio pronunciations."""

    check_lexicon: bool = False
    """Whether to check lexicon for new questions.

    If this property is set to `True`, the system will check if the new question
    is already in the lexicon.
    """

    ask_lexicon: bool = False
    """Whether to ask if the user already knows the question before adding it.

    If this property is set to `True`, the system will ask the user if they
    already know the question. The answer will be stored in the lexicon.
    """

    max_for_day: int = 10
    """Maximum number of questions per day."""
