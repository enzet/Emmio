"""Course configuration."""

from pydantic import BaseModel

from emmio.language import LanguageConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class CourseConfig(BaseModel):
    """A language-level set of learnings (e.g. vocabulary, alphabet).

    Unlike `LearningConfig`, a course has no mutable preferences of its own:
    everything beyond its identity (name and language) lives on the
    `Learning`s it contains.
    """

    name: str
    """Display name, e.g. `Armenian`."""

    language: LanguageConfig
    """The course's language."""
