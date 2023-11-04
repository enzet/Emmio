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


class Response(Enum):
    """User response to a question."""

    RIGHT = "y"
    """Question was answered correctly."""

    WRONG = "n"
    """Question was answered incorrectly."""

    SKIP = "s"
    """Question was excluded from the learning process."""


class LearningRecord(BaseModel):
    """Learning record for a question."""

    question_id: str
    """
    Unique string question identifier. For single word learning it should be a
    word itself.
    """

    response: Response
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


class LearningProcess(BaseModel):
    records: list[LearningRecord]
    """List of learning records ordered from the latest to the newest."""

    skipping: dict[str, int] = {}
    """
    Mapping from question identifier to the number of times it was skipped.
    """

    def skip(self, question_id: str) -> None:
        self.skipping[question_id] = self.skipping.get(question_id, 0) + 1


@dataclass
class Knowledge:
    """Knowledge of the question."""

    question_id: str
    responses: list[Response]
    last_record_time: datetime
    interval: timedelta

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.interval.total_seconds() != 0

    def get_depth(self) -> int:
        """Get learning depth (length of the last sequence of right answers)."""
        if Response.WRONG in self.responses:
            return list(reversed(self.responses)).index(Response.WRONG)
        return len(self.responses)

    def get_last_response(self) -> Response:
        """Get last response for the question."""
        return self.responses[-1]

    def count_wrong_answers(self) -> int:
        """Get number of times learning interval was set to minimal."""
        return self.responses.count(Response.WRONG)

    def count_responses(self) -> int:
        """Get number of responses."""
        return len(self.responses)

    def get_next_time(self) -> datetime:
        """Get next point in time question should be repeated."""
        return self.last_record_time + self.interval


class Learning:
    """Learning process."""

    def __init__(self, path: Path, config: LearnConfig, id_: str) -> None:
        self.id_: str = id_
        self.config: LearnConfig = config
        self.knowledge: dict[str, Knowledge] = {}
        self.learning_language: Language = construct_language(
            config.learning_language
        )
        self.base_languages: list[Language] = [
            construct_language(x) for x in config.base_languages
        ]
        self.file_path: Path = path / config.file_name

        # Create learning file if it doesn't exist.
        if not self.file_path.is_file():
            self.write()

        logging.info(f"Reading {self.file_path}...")
        with self.file_path.open() as log_file:
            content: dict = json.load(log_file)

        self.process: LearningProcess = LearningProcess(**content)

        for record in self.process.records:
            self.__update_knowledge(record)

    def __update_knowledge(self, record: LearningRecord) -> None:
        last_responses: list[Response] = []
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
        response: Response,
        sentence_id: int,
        question_id: str,
        interval: timedelta,
        time: datetime | None = None,
    ) -> None:
        """Register user response.

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
        self.process.records.append(record)
        self.__update_knowledge(record)
        if question_id in self.process.skipping:
            self.process.skipping.pop(question_id)

    def verify(self) -> bool:
        now: datetime = datetime.now()
        question_ids = list(self.process.skipping.keys())
        for question_id in question_ids:
            knowledge = self.knowledge[question_id]
            if knowledge.get_next_time() > now:
                return False

        return True

    def skip(self, question_id: str) -> None:
        self.process.skip(question_id)

    def __is_not_skipped(self, question_id: str) -> bool:
        return question_id not in self.process.skipping.keys()

    def __get_next_questions(self) -> list[str]:
        return [
            x
            for x in self.knowledge
            if (
                self.knowledge[x].is_learning()
                and datetime.now() > self.knowledge[x].get_next_time()
            )
        ]

    def get_skipping_counter(self, question_id: str) -> int:
        return (
            self.process.skipping[question_id]
            if question_id in self.process.skipping
            else 0
        )

    def get_next_question(self) -> str | None:
        """Get question identifier of the next question."""
        ids: list[str] = self.__get_next_questions()
        if not ids:
            return None
        return sorted(ids, key=lambda x: self.get_skipping_counter(x))[0]

    def has(self, question_id: str) -> bool:
        """Check whether the question is in the learning process."""
        return question_id in self.knowledge

    def is_initially_known(self, question_id: str) -> bool:
        """Check whether the answer to the question was initially known."""
        knowledge: Knowledge = self.knowledge[question_id]

        return (
            not knowledge.is_learning()
            and len(knowledge.responses) == 1
            and knowledge.responses[0] == Response.RIGHT
        )

    def get_nearest(self) -> datetime | None:
        """Get the nearest repetition time."""
        return min(
            self.knowledge[question_id].get_next_time()
            for question_id in self.knowledge
            if self.knowledge[question_id].is_learning()
            and self.__is_not_skipped(question_id)
        )

    def count_questions_added_today(self) -> int:
        seen: set[str] = set()
        now: datetime = datetime.now()
        today_start: datetime = datetime(
            year=now.year, month=now.month, day=now.day
        )
        count: int = 0
        for record in self.process.records:
            if (
                record.question_id not in seen
                and record.is_learning()
                and record.time > today_start
            ):
                count += 1
            seen.add(record.question_id)
        return count

    def count_questions_to_repeat(self) -> int:
        """Return the number of learning items that are being learning and ready
        to repeat at the current moment.
        """
        now: datetime = datetime.now()
        return sum(
            record.is_learning() and record.get_next_time() < now
            for question_id, record in self.knowledge.items()
        )

    def count_questions_to_learn(self) -> int:
        """Count the number of learning items that are being learning."""
        return sum(x.is_learning() for x in self.knowledge.values())

    def write(self) -> None:
        """Serialize learning process to a file."""

        logging.debug(f"Saving learning process to {self.file_path}...")

        with self.file_path.open("w+") as output_file:
            output_file.write(self.process.json(ensure_ascii=False, indent=4))

    def is_ready(self) -> bool:
        """Check whether the learning is ready for the next question."""
        return self.get_next_question() is not None

    def count_questions_to_add(self) -> int:
        """Count the number of questions before reaching the maximum."""
        return max(
            0, self.config.max_for_day - self.count_questions_added_today()
        )

    def compute_pressure(self) -> float:
        """Compute the pressure of the learning process.

        Pressure is a float characteristic of a learning process that somehow
        reflects the amount of effort needed to repeat all the questions.
        """
        return sum(
            1.0 / (2.0 ** knowledge.get_depth())
            for knowledge in self.knowledge.values()
            if knowledge.interval.total_seconds() > 0
        )

    def get_safe_question_ids(self) -> list[str]:
        """Get list of identifiers of questions, that is being learning and not
        close to be repeated.
        """
        now: datetime = datetime.now()
        return [
            x.question_id
            for x in self.knowledge.values()
            if (
                not self.is_initially_known(x.question_id)
                and x.get_last_response() != Response.SKIP
                and ((now - x.last_record_time) / x.interval) < 0.8
            )
        ]

    def compare_by_new(self) -> int:
        return self.count_questions_added_today() - self.config.max_for_day

    def compare_by_old(self) -> int:
        return -self.count_questions_to_repeat()

    def get_knowledge(self, word: str) -> Knowledge | None:
        return self.knowledge.get(word)
