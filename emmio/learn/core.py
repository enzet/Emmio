"""
The learning process.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from emmio.language import Language, construct_language
from emmio.learn.config import LearnConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

FORMAT: str = "%Y.%m.%d %H:%M:%S.%f"
SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class ResponseType(Enum):
    """Possible user responses."""

    RIGHT = "y"
    WRONG = "n"
    SKIP = "s"


@dataclass
class LearningRecord:
    """Learning record for a question."""

    question_id: str
    """
    Unique string question identifier.

    For single word learning it should be a word itself.
    """

    answer: ResponseType
    """Response type: fail or success."""

    sentence_id: int
    """Sentence identifier used to learn the question."""

    time: datetime
    """Record time."""

    interval: timedelta
    """
    Time interval for the next question.

    The question is ready to repeat after `time` + `interval` point in time.
    """

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.interval.total_seconds() != 0

    @classmethod
    def from_structure(cls, structure: dict[str, Any]) -> "LearningRecord":
        """Parse learning record from the dictionary."""

        interval = SMALLEST_INTERVAL
        if "interval" in structure:
            interval = timedelta(seconds=structure["interval"])
        return cls(
            structure["word"],
            ResponseType(structure["answer"]),
            structure["sentence_id"],
            datetime.strptime(structure["time"], FORMAT),
            interval,
        )

    def to_structure(self) -> dict[str, Any]:
        """Export learning record as a dictionary."""

        return {
            "word": self.question_id,
            "answer": self.answer.value,
            "sentence_id": self.sentence_id,
            "time": self.time.strftime(FORMAT),
            "interval": self.interval.total_seconds(),
        }


@dataclass
class Knowledge:
    """Knowledge of the question."""

    question_id: str
    responses: list[ResponseType]
    last_record_time: datetime
    interval: timedelta

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.interval.total_seconds() != 0

    def get_depth(self) -> int:
        """Get learning depth (length of the last sequence of right answers)."""
        if ResponseType.WRONG in self.responses:
            return list(reversed(self.responses)).index(ResponseType.WRONG)
        return len(self.responses)

    def get_last_answer(self) -> ResponseType:
        """Get last answer for the word."""
        return self.responses[-1]

    def get_returns(self) -> int:
        """Get number of times learning interval was set to minimal."""
        return self.responses.count(ResponseType.WRONG)

    def get_answers_number(self) -> int:
        """Get number of answers."""
        return len(self.responses)

    def get_next_time(self) -> datetime:
        """Get next point in time question should be repeated."""
        return self.last_record_time + self.interval


class Learning:
    """Learning process."""

    def __init__(self, path: Path, config: LearnConfig) -> None:

        self.config: LearnConfig = config

        self.records: list[LearningRecord] = []
        self.knowledge: dict[str, Knowledge] = {}

        self.learning_language: Language = construct_language(
            config.learning_language
        )
        self.base_language: Language = construct_language(config.base_language)

        self.file_path: Path = path / config.file_name

        # Create learning file if it doesn't exist.
        if not self.file_path.is_file():
            self.write()

        with self.file_path.open() as log_file:
            content = json.load(log_file)
            records = content["log"]

        for record_structure in records:
            record: LearningRecord = LearningRecord.from_structure(
                record_structure
            )
            self.records.append(record)
            self._update_knowledge(record)

    def _update_knowledge(self, record: LearningRecord) -> None:
        last_answers: list[ResponseType] = []
        if record.question_id in self.knowledge:
            last_answers = self.knowledge[record.question_id].responses
        self.knowledge[record.question_id] = Knowledge(
            record.question_id,
            last_answers + [record.answer],
            record.time,
            record.interval,
        )

    def register(
        self,
        answer: ResponseType,
        sentence_id: int,
        question_id: str,
        interval: timedelta,
        time: datetime | None = None,
    ) -> None:
        """
        Register user answer.

        :param answer: user response
        :param sentence_id: sentence identifier was used to learn the word
        :param question_id: question identifier
        :param interval: repeat interval
        :param time: a moment in time what the action was performed, if time is
            None, use method call time
        """
        if time is None:
            time = datetime.now()

        record: LearningRecord = LearningRecord(
            question_id, answer, sentence_id, time, interval
        )
        self.records.append(record)
        self._update_knowledge(record)

    def get_next(self, skip: set[str]) -> str | None:
        """
        Get question identifier of the next question.

        :param skip: question identifiers to skip
        """
        for question_id in self.knowledge:
            if (
                question_id not in skip
                and self.knowledge[question_id].is_learning() != 0
                and datetime.now() > self.knowledge[question_id].get_next_time()
            ):
                return question_id

    def has(self, word: str) -> bool:
        """Check whether the word is in the learning process."""
        return word in self.knowledge

    def is_initially_known(self, word: str) -> bool:
        """Check whether the word was initially known."""
        knowledge: Knowledge = self.knowledge[word]

        return (
            not knowledge.is_learning()
            and len(knowledge.responses) == 1
            and knowledge.responses[0] == ResponseType.RIGHT
        )

    def get_nearest(self, skip: set[str] = None) -> datetime | None:
        """Get the nearest repetition time."""
        return min(
            [
                self.knowledge[word].get_next_time()
                for word in self.knowledge
                if self.knowledge[word].is_learning()
                and (not skip or word not in skip)
            ]
        )

    def new_today(self) -> int:
        seen: set[str] = set()
        now: datetime = datetime.now()
        today_start: datetime = datetime(
            year=now.year, month=now.month, day=now.day
        )
        count: int = 0
        for record in self.records:
            if (
                record.question_id not in seen
                and record.is_learning()
                and record.time > today_start
            ):
                count += 1
            seen.add(record.question_id)
        return count

    def to_repeat(self, skip: set[str] = None) -> int:
        count: int = 0
        now: datetime = datetime.now()
        for word in self.knowledge:
            record: Knowledge = self.knowledge[word]
            if (
                record.is_learning()
                and record.get_next_time() < now
                and (not skip or word not in skip)
            ):
                count += 1
        return count

    def learning(self) -> int:
        count: int = 0
        for word in self.knowledge:
            record: Knowledge = self.knowledge[word]
            if record.is_learning():
                count += 1
        return count

    def write(self) -> None:
        """Serialize learning process to a file."""
        logging.debug(f"saving learning process to {self.file_path}")
        structure = {"log": []}
        for record in self.records:
            structure["log"].append(record.to_structure())
        with self.file_path.open("w+") as output_file:
            json.dump(structure, output_file, ensure_ascii=False, indent=4)

    def is_ready(self, skip) -> bool:
        """Check whether the learning is ready for the next word."""
        return self.get_next(skip) is not None
