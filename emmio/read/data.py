from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from emmio.read.config import ReadConfig
from emmio.read.core import Read


class ReadSession:
    time_interval: list[datetime]
    sentence_interval: list[int]


@dataclass
class ReadData:
    """Manages directory with reading processes."""

    path: Path
    read_processes: dict[str, Read] = field(default_factory=dict)

    @classmethod
    def from_config(cls, path: Path, config: dict):
        read_processes: dict[str, Read] = {}

        for read_id, read_config in config.items():
            read_processes[read_id] = Read.from_config(
                path, ReadConfig(**read_config)
            )

        return cls(path, read_processes)

    def get_read_processes(self):
        return self.read_processes
