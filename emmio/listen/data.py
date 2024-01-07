from dataclasses import dataclass
from pathlib import Path

from emmio.listen.config import ListenConfig
from emmio.listen.core import Listening


@dataclass
class ListenData:
    path: Path
    listenings: dict[str, Listening]

    @classmethod
    def from_config(cls, path: Path, config: dict) -> "ListenData":
        listenings: dict[str, Listening] = {
            listen_id: Listening(path, ListenConfig(**learn_config), listen_id)
            for listen_id, learn_config in config.items()
        }
        return cls(path, listenings)

    def get_listening(self, listening_id: str) -> Listening:
        return self.listenings[listening_id]
