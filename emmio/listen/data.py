"""Data for listening."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from emmio.listen.config import ListenConfig
from emmio.listen.core import Listening


@dataclass
class ListenData:
    """Data for listening."""

    path: Path
    """Path to the directory managed by this class."""

    listenings: dict[str, Listening] = field(default_factory=dict)
    """Mapping from listening identifiers to listening processes."""

    @classmethod
    def from_config(cls, path: Path, config: dict) -> Self:
        """Initialize listen data from the configuration.

        :param path: path to the directory with listen data
        :param config: configuration for listen data
        """
        listenings: dict[str, Listening] = {
            listen_id: Listening.from_config(
                path, listen_id, ListenConfig(**learn_config)
            )
            for listen_id, learn_config in config.items()
        }
        return cls(path, listenings)

    def get_listening(self, listening_id: str) -> Listening:
        """Get listening by its identifier.

        :param listening_id: identifier of the listening
        :return: listening process
        """
        return self.listenings[listening_id]
