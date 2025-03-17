"""The learning process."""

import json
import logging
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, override

import yaml
from pydantic.main import BaseModel

from emmio.core import Record, Session
from emmio.language import Language, construct_language
from emmio.learn.config import LearnConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

FORMAT: str = "%Y.%m.%d %H:%M:%S.%f"
MULTIPLIER: float = 2.0


class Response(Enum):
    """User response to a question."""

    RIGHT = "y"
    """Question was answered correctly."""

    WRONG = "n"
    """Question was answered incorrectly."""

    SKIP = "s"
    """Question was excluded from the learning process."""

    POSTPONE = "p"
    """Question was postponed."""

    def get_symbol(self) -> str:
        """Get short symbol for the response."""
        match self:
            case Response.RIGHT:
                return "-"
            case Response.WRONG:
                return "/"
            case Response.SKIP:
                return "X"
            case Response.POSTPONE:
                return ">"


class LearningRecord(Record):
    """Learning record for a question."""

    question_id: str
    """Unique string question identifier.

    For single word learning it should be a word itself.
    """

    response: Response
    """Response type: fail or success."""

    sentence_id: int
    """Sentence identifier used to learn the question."""

    @override
    def get_symbol(self) -> str:
        """Get short symbol for the learning record."""
        return self.response.get_symbol()


class LearningSession(BaseModel, Session):
    """Learning session.

    It is assumed that all time spent in the session is spent in learning.
    """

    type: str
    """Session type."""

    start: datetime
    """The time when the session was started."""

    end: datetime | None = None
    """The time when the session was finished."""

    actions: int | None = None
    """Number of actions recorded in the session."""

    def get_start(self) -> datetime:
        return self.start

    def get_end(self) -> datetime | None:
        return self.end

    def end_session(self, time: datetime, actions: int) -> None:
        self.actions = actions
        self.end = time

    def get_time(self) -> timedelta | None:
        if self.end is None:
            return None
        return self.end - self.start


class LearningProcess(BaseModel):
    """Learning process: collection of all learning records and sessions."""

    records: list[LearningRecord]
    """List of learning records ordered from the latest to the newest."""

    sessions: list[LearningSession] = []
    """Recorded leaning sessions."""

    def __len__(self) -> int:
        return len(self.records)


@dataclass
class Knowledge:
    """Knowledge of the question: list of learning records."""

    question_id: str
    """Question identifier."""

    records: list[LearningRecord]
    """List of learning records ordered from the latest to the newest."""

    def __post_init__(self):
        assert self.records, "Knowledge should contain at least one record."
        self.__responses = [x.response for x in self.records]

    def get_last_record(self) -> LearningRecord:
        """Get the latest learning record."""
        return self.records[-1]

    def get_responses(self) -> list[Response]:
        """Get list of responses."""
        return self.__responses

    def get_last_response(self) -> Response:
        """Get last response for the question."""
        return self.records[-1].response

    def is_learning(self) -> bool:
        """Is the question should be repeated in the future."""
        return self.get_last_response() != Response.SKIP and not (
            len(self.__responses) == 1 and self.__responses[0] == Response.RIGHT
        )

    def get_depth(self) -> int:
        """Get learning depth (length of the last sequence of right answers)."""
        if Response.WRONG in self.__responses:
            return list(reversed(self.__responses)).index(Response.WRONG)
        return len(self.__responses)

    def count_wrong_answers(self) -> int:
        """Get number of times learning interval was set to minimal."""
        return self.__responses.count(Response.WRONG)

    def count_right_streak(self) -> int:
        """Get number of right answers after the last wrong answer."""
        result: int = 0
        for response in self.__responses[::-1]:
            if response == Response.RIGHT:
                result += 1
            elif response == Response.POSTPONE:
                continue
            else:
                break
        return result

    def count_responses(self) -> int:
        """Get number of responses."""
        return len(self.__responses)

    def add_record(self, record: LearningRecord) -> None:
        """Add a learning record."""
        self.records.append(record)
        self.__responses.append(record.response)

    def added_time(self) -> datetime:
        """Get the time when the question was added."""
        return self.records[0].time

    def get_records(self) -> list[LearningRecord]:
        """Get list of learning records."""
        return self.records

    def estimate(self, point: datetime) -> float:
        """Estimate the knowledge of the question at the given point in time."""
        last_record = self.get_last_record()
        right_streak: int = self.count_right_streak()
        if right_streak == 0:
            seconds = 300.0
        elif right_streak == 1:
            seconds = 86400.0
        else:
            right_records: list[LearningRecord] = [
                x for x in self.get_records() if x.response == Response.RIGHT
            ]
            seconds = (
                right_records[-1].time - right_records[-2].time
            ).total_seconds() * MULTIPLIER
        if not seconds:
            return 0.0
        return (point - last_record.time).total_seconds() / seconds


class Learning:
    """Learning process."""

    def __init__(self, path: Path, config: LearnConfig, id_: str) -> None:

        self.id_: str = id_
        """Unique identifier of the learning process."""

        self.config: LearnConfig = config
        """Learning configuration."""

        self.knowledge: dict[str, Knowledge] = {}
        """Mapping from question identifiers to their knowledge data."""

        self.learning_language: Language = construct_language(
            config.learning_language
        )
        self.base_languages: list[Language] = [
            construct_language(x) for x in config.base_languages
        ]
        self.file_path: Path = path / config.file_name

        self.process: LearningProcess

        # Create learning file if it doesn't exist.
        if not self.file_path.is_file():
            self.process = LearningProcess(records=[])
            self.write()
        elif self.file_path.name.endswith(".json"):
            logging.info("Reading `%s`...", self.file_path)
            with self.file_path.open(encoding="utf-8") as log_file:
                try:
                    self.process = LearningProcess(**(json.load(log_file)))
                except json.decoder.JSONDecodeError:
                    logging.fatal("Cannot process file `%s`.", self.file_path)
                    sys.exit(1)
        elif self.file_path.name.endswith(".yml"):
            logging.info("Reading `%s`...", self.file_path)
            self.process = load_old_format(self.file_path)
        else:
            raise ValueError("Unknown file format: `%s`.", self.file_path.name)

        for record in self.process.records:
            self.__update_knowledge(record)

    def __update_knowledge(self, record: LearningRecord) -> None:
        question_id: str = record.question_id
        if question_id not in self.knowledge:
            self.knowledge[question_id] = Knowledge(question_id, [record])
        else:
            self.knowledge[question_id].add_record(record)

    def register(
        self,
        response: Response,
        sentence_id: int,
        question_id: str,
        time: datetime | None = None,
        request_time: datetime | None = None,
    ) -> None:
        """Register user response.

        :param response: user response
        :param sentence_id: sentence identifier was used to learn the word
        :param question_id: question identifier
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
            request_time=request_time,
        )
        self.process.records.append(record)
        self.__update_knowledge(record)

    def postpone(self, question_id: str) -> None:
        self.register(Response.POSTPONE, 0, question_id)

    def get_postpone_time(self) -> timedelta:
        if self.config.scheme and self.config.scheme.postpone_time:
            return timedelta(seconds=self.config.scheme.postpone_time)
        return timedelta(days=2)

    def get_next_time(self, knowledge: Knowledge) -> datetime:
        return knowledge.get_last_record().time + self.get_interval(knowledge)

    def get_interval(self, knowledge: Knowledge) -> timedelta:
        if knowledge.get_last_response() == Response.POSTPONE:
            return self.get_postpone_time()
        seconds: float
        right_streak: int = knowledge.count_right_streak()
        if right_streak == 0:
            seconds = 3600.0
        elif right_streak == 1:
            seconds = 86400.0
        else:
            right_records: list[LearningRecord] = [
                x
                for x in knowledge.get_records()
                if x.response == Response.RIGHT
            ]
            seconds = (
                right_records[-1].time - right_records[-2].time
            ).total_seconds() * (MULTIPLIER + ((random.random() - 0.5) * 0.0))
        return timedelta(seconds=seconds)

    def __get_next_questions(self) -> list[Knowledge]:
        now: datetime = datetime.now()
        return [
            x
            for x in self.knowledge.values()
            if (x.is_learning() and now > self.get_next_time(x))
        ]

    def get_next_question(self) -> str | None:
        """Get question identifier of the next question."""
        knowledge: list[Knowledge] = self.__get_next_questions()
        if not knowledge:
            return None
        knowledge = sorted(knowledge, key=lambda x: self.get_next_time(x))
        return knowledge[0].question_id

    def has(self, question_id: str) -> bool:
        """Check whether the question is in the learning process."""
        return question_id in self.knowledge

    def is_initially_known(self, question_id: str) -> bool:
        """Check whether the answer to the question was initially known."""

        knowledge: Knowledge = self.knowledge[question_id]

        return (
            not knowledge.is_learning()
            and len(knowledge.get_responses()) == 1
            and knowledge.get_responses()[0] == Response.RIGHT
        )

    def get_nearest(self) -> datetime | None:
        """Get the nearest repetition time."""

        if times := [
            self.get_next_time(self.knowledge[question_id])
            for question_id in self.knowledge
            if self.knowledge[question_id].is_learning()
        ]:
            return min(times)

        return None

    def count_questions_added_today(self) -> int:
        """Count questions added today and in learning process."""

        now: datetime = datetime.now()
        today_start: datetime = datetime(
            year=now.year, month=now.month, day=now.day
        )
        return len(
            [
                knowledge
                for knowledge in self.knowledge.values()
                if knowledge.is_learning()
                and knowledge.added_time() > today_start
            ]
        )

    def count_questions_to_repeat(self) -> int:
        """Return the number of learning items that are being learning and ready
        to repeat at the current moment.
        """
        now: datetime = datetime.now()
        return sum(
            x.is_learning() and self.get_next_time(x) < now
            for x in self.knowledge.values()
        )

    def count_questions_to_learn(self) -> int:
        """Count the number of learning items that are being learning."""
        return sum(x.is_learning() for x in self.knowledge.values())

    def write(self) -> None:
        """Serialize learning process to a file."""
        if self.file_path.name.endswith(".json"):
            logging.debug("Saving learning process to `%s`...", self.file_path)
            with self.file_path.open("w+", encoding="utf-8") as output_file:
                output_file.write(self.process.model_dump_json(indent=4))

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
            1.0 / (MULTIPLIER ** knowledge.get_depth())
            for knowledge in self.knowledge.values()
            if knowledge.is_learning()
        )

    def get_safe_question_ids(self) -> list[str]:
        """Get list of identifiers of questions, that is being learning and not
        close to be repeated.
        """
        now: datetime = datetime.now()
        return [
            x.question_id
            for x in self.knowledge.values()
            if x.is_learning() and x.estimate(now) < 0.5
        ]

    def compare_by_new(self) -> int:
        return self.count_questions_added_today() - self.config.max_for_day

    def compare_by_old(self) -> int:
        return -self.count_questions_to_repeat()

    def get_knowledge(self, word: str) -> Knowledge | None:
        return self.knowledge.get(word)

    def get_actions(self) -> int:
        """Get number of meaningful user actions.

        Meaningful actions are those with `RIGHT` or `WRONG` answer.
        """
        return self.count_actions(types=(Response.RIGHT, Response.WRONG))

    def count_postponed(self) -> int:
        """Count the number of questions that were postponed."""
        return self.count_actions(types=(Response.POSTPONE,))

    def count_actions(
        self,
        since: datetime | None = None,
        types: tuple[Response, ...] = (Response.RIGHT, Response.WRONG),
    ) -> int:
        """Count actions of the given types."""

        return sum(
            1
            for record in self.process.records
            if record.response in types and (not since or record.time > since)
        )

    def get_records(self) -> list[LearningRecord]:
        return self.process.records

    def get_sessions(self) -> list[LearningSession]:
        return self.process.sessions

    def compute_average_action_time(self) -> timedelta:
        """Compute average time needed for an action recorded in sessions."""

        total_time: timedelta = timedelta(0)
        total_actions: int = 0

        for session in self.process.sessions:
            time: timedelta | None = session.get_time()
            if time:
                total_time += time
                total_actions += session.actions or 0

        if total_actions:
            return total_time / total_actions

        return timedelta(0)


def time_format(minutes: int) -> datetime:
    return datetime(1970, 1, 1) + timedelta(seconds=minutes * 60)


def load_old_format(path: Path):
    with path.open(encoding="utf-8") as input_file:
        process: dict[str, dict[str, Any]] = yaml.load(
            input_file, Loader=yaml.FullLoader
        )
    added: set[datetime] = set()
    learning_records: list[LearningRecord] = []
    for question_id, records in process.items():
        if (
            "answers" in records
            and records["answers"] != "y"
            and records["plan"] != 1_000_000_000
        ):
            if "added" in records:
                added.add(time_format(records["added"]))
            answers: str = records["answers"]
            interval: int = 1
            intervals: list[int] = []
            time = 0
            array: list[int] = []
            for letter in answers:
                interval = 1 if letter == "n" else interval * 2
                array.append(time)
                intervals.append(interval)
                time += interval
            times = [
                time_format(records["last"])
                + timedelta(seconds=(x - array[-1]) * 24 * 60 * 60)
                for x in array
            ]
            for delta, answer, interval in zip(times, answers, intervals):
                record: LearningRecord = LearningRecord(
                    question_id=str(question_id),
                    response=(
                        Response.RIGHT if answer == "y" else Response.WRONG
                    ),
                    sentence_id=0,
                    time=delta,
                )
                learning_records.append(record)

    return LearningProcess(records=learning_records)
