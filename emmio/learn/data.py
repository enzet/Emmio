from dataclasses import dataclass
from pathlib import Path

from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class LearnData:
    """Manages the directory with the learning data."""

    path: Path
    """The directory managed by this class."""

    learnings: dict[str, Learning]
    """Mapping from learning ids to learning processes."""

    @classmethod
    def from_config(cls, path: Path, config: dict) -> "LearnData":

        return cls(
            path,
            {
                learn_id: Learning(path, LearnConfig(**learn_config))
                for learn_id, learn_config in config.items()
            },
        )
