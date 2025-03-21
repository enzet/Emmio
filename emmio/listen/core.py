"""Core functionality for listening."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Self, override

from pydantic import BaseModel

from emmio.core import Record
from emmio.listen.config import ListenConfig
from emmio.user.core import UserArtifact

PAUSE_AFTER_PLAY: float = 2.0


class ListeningRecord(Record):
    """Record of one listening."""

    word: str
    """Word in the learning language that was listened."""

    translations: list[str]
    """Translations of the word in the base language."""

    @override
    def get_symbol(self) -> str:
        return "L"


class ListeningProcess(BaseModel):
    """Process of listening."""

    records: list[ListeningRecord]
    """Records of listening."""

    def register(self, record: ListeningRecord) -> None:
        """Register new record of listening."""
        self.records.append(record)


@dataclass
class Listening(UserArtifact):
    """Listening process."""

    process: ListeningProcess
    """Listening process."""

    config: ListenConfig
    """Configuration of the listening process."""

    _words_cache: dict[str, int]
    """Cache of how many times the word was heard."""

    _records_cache: dict[str, list[ListeningRecord]]
    """Cache of records of how the word was heard."""

    @classmethod
    def from_config(cls, path: Path, id_: str, config: ListenConfig) -> Self:
        """Initialize listening process."""

        file_path: Path = path / config.file_name

        process: ListeningProcess
        if not file_path.is_file():
            process = ListeningProcess(records=[])
        else:
            with file_path.open(encoding="utf-8") as input_file:
                process = ListeningProcess(**json.load(input_file))

        words_cache: dict[str, int] = defaultdict(int)
        for record in process.records:
            words_cache[record.word] += 1

        records_cache: dict[str, list[ListeningRecord]] = defaultdict(list)
        for record in process.records:
            records_cache[record.word].append(record)

        return cls(
            id_,
            file_path,
            process,
            config,
            words_cache,
            records_cache,
        )

    @override
    def dump_json(self) -> str:
        """Serialize listening process to a JSON string."""
        return self.process.model_dump_json(indent=4)

    def register(self, word: str, translations: list[str]) -> None:
        """Register new record of listening."""

        record: ListeningRecord = ListeningRecord(
            word=word, translations=translations, time=datetime.now()
        )
        self.process.register(record)
        self._words_cache[word] += 1
        self._records_cache[word].append(record)
        self.write()

    def get_hearings(self, word: str) -> int:
        """Get number of how many times the word was heard."""
        return self._words_cache.get(word, 0)

    def get_records(self, word: str) -> list[ListeningRecord]:
        """Get records of how the word was heard."""
        return self._records_cache.get(word, [])
