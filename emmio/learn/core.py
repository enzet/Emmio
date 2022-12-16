"""The learning process."""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from pydantic.main import BaseModel

from emmio.language import Language, construct_language
from emmio.learn.config import LearnConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

FORMAT: str = "%Y.%m.%d %H:%M:%S.%f"
SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class ResponseType(Enum):
    """Possible user responses."""

    RIGHT = "y"
    """Question was answered correctly."""

    WRONG = "n"
    """Question was answered incorrectly."""

    SKIP = "s"
    """Question was skipped."""


class LearningRecord(BaseModel):
    """Learning record for a question."""

    question_id: str
    """
    Unique string question identifier. For single word learning it should be a
    word itself.
    """

    response: ResponseType
    """Response type: fail or success."""

    sentence_id: int
    """Sentence identifier used to learn the question."""

    time: datetime
    """Record time."""

    interval: timedelta = SMALLEST_INTERVAL
    """
    Time interval for the next question. The question is ready to repeat after
    `time` + `interval` point in time.
    """

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.interval.total_seconds() != 0


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

    def get_last_response(self) -> ResponseType:
        """Get last response for the question."""
        return self.responses[-1]

    def count_wrong_answers(self) -> int:
        """Get number of times learning interval was set to minimal."""
        return self.responses.count(ResponseType.WRONG)

    def count_responses(self) -> int:
        """Get number of responses."""
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

        logging.info(f"Reading {self.file_path}...")
        with self.file_path.open() as log_file:
            content = json.load(log_file)
            records = content["log"]

        for record_structure in records:
            record: LearningRecord = LearningRecord(**record_structure)
            self.records.append(record)
            self._update_knowledge(record)

    def _update_knowledge(self, record: LearningRecord) -> None:
        last_responses: list[ResponseType] = []
        if record.question_id in self.knowledge:
            last_responses = self.knowledge[record.question_id].responses
        self.knowledge[record.question_id] = Knowledge(
            record.question_id,
            last_responses + [record.response],
            record.time,
            record.interval,
        )

    def register(
        self,
        response: ResponseType,
        sentence_id: int,
        question_id: str,
        interval: timedelta,
        time: datetime | None = None,
    ) -> None:
        """
        Register user response.

        :param response: user response
        :param sentence_id: sentence identifier was used to learn the word
        :param question_id: question identifier
        :param interval: repeat interval
        :param time: a moment in time what the action was performed, if time is
            None, use method call time
        """
        if time is None:
            time = datetime.now()

        record: LearningRecord = LearningRecord(
            question_id=question_id,
            response=response,
            sentence_id=sentence_id,
            time=time,
            interval=interval,
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

    def has(self, question_id: str) -> bool:
        """Check whether the question is in the learning process."""
        return question_id in self.knowledge

    def is_initially_known(self, question_id: str) -> bool:
        """Check whether the answer to the question was initially known."""
        knowledge: Knowledge = self.knowledge[question_id]

        return (
            not knowledge.is_learning()
            and len(knowledge.responses) == 1
            and knowledge.responses[0] == ResponseType.RIGHT
        )

    def get_nearest(self, skip: set[str] = None) -> datetime | None:
        """Get the nearest repetition time."""
        return min(
            self.knowledge[question_id].get_next_time()
            for question_id in self.knowledge
            if self.knowledge[question_id].is_learning()
            and (not skip or question_id not in skip)
        )

    def count_questions_added_today(self) -> int:
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

    def count_questions_to_repeat(self, skip: set[str] = None) -> int:
        """
        Return the number of learning items that are being learning, not
        skipped, and ready to repeat at the current moment.
        """
        now: datetime = datetime.now()
        return sum(
            (
                record.is_learning()
                and record.get_next_time() < now
                and (not skip or question_id not in skip)
            )
            for question_id, record in self.knowledge.items()
        )

    def count_questions_to_learn(self) -> int:
        """Count the number of learning items that are being learning."""
        return sum(x.is_learning() for x in self.knowledge.values())

    def write(self) -> None:
        """Serialize learning process to a file."""
        logging.debug(f"saving learning process to {self.file_path}")
        structure = {"log": []}
        for record in self.records:
            # FIXME: pretty dirty quick fix.
            structure["log"].append(json.loads(record.json()))
        with self.file_path.open("w+") as output_file:
            json.dump(structure, output_file, ensure_ascii=False, indent=4)

    def is_ready(self, skip) -> bool:
        """Check whether the learning is ready for the next question."""
        return self.get_next(skip) is not None
