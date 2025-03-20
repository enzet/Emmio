"""User artifacts: learning, lexicon checking, listening."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from emmio import util


@dataclass
class UserArtifact(ABC):
    """User artifact."""

    id_: str
    """Unique identifier of the artifact."""

    file_path: Path
    """Path to the artifact file."""

    @abstractmethod
    def dump_json(self) -> str:
        """Serialize user artifact data to a JSON string."""
        raise NotImplementedError()

    def write(self) -> None:
        """Serialize user artifact data to a JSON file."""

        if self.file_path.name.endswith(".json"):
            logging.debug("Saving learning process to `%s`...", self.file_path)
            util.write_atomic(self.file_path, self.dump_json())
        else:
            raise ValueError(f"Unknown file format: `{self.file_path.name}`.")
