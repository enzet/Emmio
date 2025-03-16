import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from emmio.listen.config import ListenConfig

PAUSE_AFTER_PLAY: float = 2.0


class ListeningRecord(BaseModel):
    word: str
    translations: list[str]
    time: datetime

    def get_symbol(self) -> str:
        return "L"


class ListeningProcess(BaseModel):
    records: list[ListeningRecord]

    def register(self, record: ListeningRecord):
        self.records.append(record)


class Listening:
    def __init__(self, path: Path, config: ListenConfig, id_: str):
        self.path: Path = path
        self.config: ListenConfig = config
        self.id_: str = id_

        self.file_path: Path = path / config.file_name

        self.process: ListeningProcess
        if not self.file_path.is_file():
            self.process = ListeningProcess(records=[])
            self.write()
        else:
            with self.file_path.open(encoding="utf-8") as input_file:
                self.process = ListeningProcess(**json.load(input_file))

        self.__words_cache: dict[str, int] = defaultdict(int)
        for record in self.process.records:
            self.__words_cache[record.word] += 1

        self.__records_cache: dict[str, list[ListeningRecord]] = defaultdict(
            list
        )
        for record in self.process.records:
            self.__records_cache[record.word].append(record)

    def write(self) -> None:
        """Write data to the output file."""
        temp_path: Path = self.file_path.with_suffix(".temp")

        with temp_path.open("w+", encoding="utf-8") as output_file:
            data = self.process.json(ensure_ascii=False, indent=4)
            output_file.write(data)

        temp_path.replace(self.file_path)

    def register(self, word: str, translations: list[str]) -> None:
        record: ListeningRecord = ListeningRecord(
            word=word, translations=translations, time=datetime.now()
        )
        self.process.register(record)
        self.__words_cache[word] += 1
        self.__records_cache[word].append(record)
        self.write()

    def get_hearings(self, word: str) -> int:
        return self.__words_cache.get(word, 0)

    def get_records(self, word: str) -> list[ListeningRecord]:
        return self.__records_cache.get(word, [])
