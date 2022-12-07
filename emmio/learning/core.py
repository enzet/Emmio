"""
The learning process.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from emmio.language import Language, construct_language
from emmio.ui import log

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

    # Unique string question identifier. For single word learning it should be
    # a word itself.
    question_id: str

    # Response type: fail or success.
    answer: ResponseType

    # Sentence identifier used to learn the question.
    sentence_id: int

    # Record time.
    time: datetime

    # Time interval for the next question. The question is ready to repeat after
    # `time` + `interval` point in time.
    interval: timedelta

    # Learning process identifier.
    course_id: str

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.interval.total_seconds() != 0

    @classmethod
    def from_structure(
        cls, structure: dict[str, Any], course_id: str
    ) -> "LearningRecord":
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
            course_id,
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
        """
        Get learning depth (length of the last consequence of right answers).
        """
        if ResponseType.WRONG in self.responses:
            return list(reversed(self.responses)).index(ResponseType.WRONG)
        else:
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

    def __init__(
        self, file_path: Path, config: dict[str, any], course_id: str
    ) -> None:
        self.file_path: Path = file_path
        self.records: list[LearningRecord] = []
        self.knowledges: dict[str, Knowledge] = {}
        self.config: dict[str, str] = config
        self.course_id: str = course_id

        # Create learning file if it doesn't exist.
        if not self.file_path.is_file():
            self.write()

        with self.file_path.open() as log_file:
            content = json.load(log_file)
            records = content["log"]

        self.frequency_list_ids: list[str] = config["frequency_lists"]

        # Config defaults.
        self.ratio: int = self.config.get("ratio", 10)
        self.language: Optional[Language] = None
        self.subject: Optional[str] = self.config.get("subject", None)
        self.check_lexicon = self.config.get("check_lexicon", True)
        self.ask_lexicon = self.config.get("ask_lexicon", False)
        self.name: str = self.config.get("name", "Unknown")
        self.is_learning: bool = self.config.get("is_learning", True)

        if "language" in self.config:
            self.language = construct_language(self.config["language"])

        for record_structure in records:
            record: LearningRecord = LearningRecord.from_structure(
                record_structure, self.course_id
            )
            self.records.append(record)
            self._update_knowledge(record)

    def _update_knowledge(self, record: LearningRecord) -> None:
        last_answers: list[ResponseType] = []
        if record.question_id in self.knowledges:
            last_answers = self.knowledges[record.question_id].responses
        self.knowledges[record.question_id] = Knowledge(
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
        time: Optional[datetime] = None,
    ) -> None:
        """
        Register student answer.

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
            question_id,
            answer,
            sentence_id,
            time,
            interval,
            self.course_id,
        )
        self.records.append(record)
        self._update_knowledge(record)

    def get_next(self, skip: set[str]) -> Optional[str]:
        """
        Get question identifier of the next question.

        :param skip: question identifiers to skip
        """
        for question_id in self.knowledges:
            if (
                question_id not in skip
                and self.knowledges[question_id].is_learning() != 0
                and datetime.now()
                > self.knowledges[question_id].get_next_time()
            ):
                return question_id

    def has(self, word: str) -> bool:
        """Check whether the word is in the learning process."""
        return word in self.knowledges

    def is_initially_known(self, word: str) -> bool:
        """Check whether the word was initially known."""
        knowledge: Knowledge = self.knowledges[word]

        return (
            not knowledge.is_learning()
            and len(knowledge.responses) == 1
            and knowledge.responses[0] == ResponseType.RIGHT
        )

    def get_nearest(self, skip: set[str] = None) -> Optional[datetime]:
        """Get nearest repetition time."""
        return min(
            [
                self.knowledges[word].get_next_time()
                for word in self.knowledges
                if self.knowledges[word].is_learning()
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
        for word in self.knowledges:
            record: Knowledge = self.knowledges[word]
            if (
                record.is_learning()
                and record.get_next_time() < now
                and (not skip or word not in skip)
            ):
                count += 1
        return count

    def learning(self) -> int:
        count: int = 0
        for word in self.knowledges:
            record: Knowledge = self.knowledges[word]
            if record.is_learning():
                count += 1
        return count

    def write(self) -> None:
        """Serialize learning process to a file."""
        log(f"saving learning process to {self.file_path}")
        structure = {"log": [], "config": self.config}
        for record in self.records:
            structure["log"].append(record.to_structure())
        with self.file_path.open("w+") as output_file:
            json.dump(structure, output_file, ensure_ascii=False, indent=4)

    def is_ready(self, skip) -> bool:
        """Check whether the learning is ready for the next word."""
        return self.get_next(skip) is not None
