"""Configuration of a user."""

from emmio.learn.config import LearningConfigType
from emmio.lexicon.config import LexiconConfigType
from emmio.listen.config import ListenConfigType

UserConfigType = dict[
    str,
    str  # For `id` and `name`.
    | dict[str, LearningConfigType]  # For `learn`.
    | dict[str, LexiconConfigType]  # For `lexicon`.
    | dict[str, ListenConfigType],  # For `listen`.
]
