from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from emmio.language import Language
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class LearnData:
    """Manages the directory with the learning data for a user.

    The directory is usually located in Emmio root directory →
    user directory → `learn` and contains JSON files with learning process.
    """

    path: Path
    """Path to the directory managed by this class."""

    learnings: dict[str, Learning] = field(default_factory=dict)
    """Mapping from learning identifiers to learning processes."""

    @classmethod
    def from_config(cls, path: Path, config: dict) -> "LearnData":
        """Initialize learn data from the configuration."""
        learnings: dict[str, Learning] = {
            learn_id: Learning(path, LearnConfig(**learn_config), learn_id)
            for learn_id, learn_config in config.items()
        }
        return cls(path, learnings)

    def get_learning(self, id_: str) -> Learning:
        """Get learning by its identifier."""
        return self.learnings[id_]

    def get_active_learnings(self) -> Iterator[Learning]:
        """Get all learnings marked as active."""
        return (x for x in self.learnings.values() if x.config.is_active)

    def get_learnings(self) -> Iterator[Learning]:
        """Get all learnings marked as active."""
        return iter(self.learnings.values())

    def compute_pressure(self):
        """Compute the sum of pressures of all learning processes.

        See ``Learning.compute_pressure``.
        """
        return sum(x.compute_pressure() for x in self.learnings.values())

    def get_learnings_by_language(self, language: Language) -> list[Learning]:
        return [
            learning
            for learning in self.learnings.values()
            if learning.learning_language == language
        ]

    def count_postponed(self):
        return sum(x.count_postponed() for x in self.learnings.values())

    def count_actions(self, since: datetime):
        return sum(
            x.count_actions(since=since) for x in self.learnings.values()
        )
