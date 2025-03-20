"""Data of learning processes."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Self

from emmio.language import Language
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning, Response

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
    def from_config(cls, path: Path, config: dict) -> Self:
        """Initialize learn data from the configuration."""
        learnings: dict[str, Learning] = {
            learn_id: Learning.from_config(
                path, LearnConfig(**learn_config), learn_id
            )
            for learn_id, learn_config in config.items()
        }
        return cls(path, learnings)

    def get_learning(self, id_: str) -> Learning:
        """Get learning by its identifier."""
        if id_ not in self.learnings:
            raise ValueError(f"Learning with id `{id_}` not found.")
        return self.learnings[id_]

    def get_active_learnings(self) -> Iterator[Learning]:
        """Get all learnings marked as active."""
        return (x for x in self.learnings.values() if x.config.is_active)

    def get_learnings(self) -> Iterator[Learning]:
        """Get all learnings marked as active."""
        return iter(self.learnings.values())

    def compute_pressure(self) -> float:
        """Compute the sum of pressures of all learning processes.

        See `Learning.compute_pressure`.
        """
        return sum(
            learning.compute_pressure() for learning in self.learnings.values()
        )

    def get_learnings_by_language(self, language: Language) -> list[Learning]:
        """Get learnings by the language.

        :param language: language
        :return: list of learnings
        """
        return [
            learning
            for learning in self.learnings.values()
            if learning.learning_language == language
        ]

    def count_postponed(self) -> int:
        """Count questions that were postponed."""
        return sum(x.count_postponed() for x in self.learnings.values())

    def count_actions(
        self,
        since: datetime,
        types: tuple[Response, ...] = (Response.RIGHT, Response.WRONG),
    ) -> int:
        """Count actions of the given types.

        :param since: since when to count
        :param types: types of actions to count
        :return: number of actions
        """
        return sum(
            x.count_actions(since, types) for x in self.learnings.values()
        )
