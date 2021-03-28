"""
The learning process.
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from emmio.language import Language
from emmio.ui import log

FORMAT: str = "%Y.%m.%d %H:%M:%S.%f"
SMALLEST_INTERVAL: timedelta = timedelta(days=1)


class ResponseType(Enum):
    """ Possible user responses. """
    RIGHT = "y"
    WRONG = "n"
    SKIP = "s"


@dataclass
class Record:
    """ Learning record for a question. """
    question_id: str
    answer: ResponseType
    sentence_id: int
    time: datetime
    interval: timedelta

    def is_learning(self) -> bool:
        """ Is the question should be repeated in the future. """
        return self.interval.total_seconds() != 0

    @classmethod
    def from_structure(cls, structure: Dict[str, Any]) -> "Record":
        """ Parse learning record from the dictionary. """
        interval = SMALLEST_INTERVAL
        if "interval" in structure:
            interval = timedelta(seconds=structure["interval"])
        return cls(
            structure["word"], ResponseType(structure["answer"]),
            structure["sentence_id"],
            datetime.strptime(structure["time"], FORMAT), interval)

    def to_structure(self) -> Dict[str, Any]:
        """ Export learning record as a dictionary. """
        return {
            "word": self.question_id, "answer": self.answer.value,
            "sentence_id": self.sentence_id,
            "time": self.time.strftime(FORMAT),
            "interval": self.interval.total_seconds()}


@dataclass
class Knowledge:
    """ Knowledge of the question. """
    question_id: str
    responses: List[ResponseType]
    last_record_time: datetime
    interval: timedelta

    def is_learning(self) -> bool:
        """ Is the question should be repeated in the future. """
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
        """ Get last answer for the word. """
        return self.responses[-1]

    def get_returns(self) -> int:
        """ Get number of times learning interval was set to minimal. """
        return self.responses.count(ResponseType.WRONG)

    def get_answers_number(self) -> int:
        """ Get number of answers. """
        return len(self.responses)

    def get_next_time(self) -> datetime:
        """ Get next point in time question should be repeated. """
        return self.last_record_time + self.interval


class Learning:
    """ Learning process. """
    def __init__(self, file_name: str, course_id: str):
        self.file_name: str = file_name
        self.records: List[Record] = []
        self.knowledges: Dict[str, Knowledge] = {}
        self.config = {}

        # Create learning file if it doesn't exist.
        if not os.path.isfile(self.file_name):
            self.write()

        with open(self.file_name) as log_file:
            content = json.load(log_file)
            records = content["log"]
            self.config = content["config"]

        log(f"loading learning process from {file_name}")

        self.frequency_list_ids: List[str] = self.config["frequency_lists"]

        # Config defaults.
        self.ratio = 10
        self.language = None
        self.subject: Optional[str] = None
        self.check_lexicon = True
        self.name: str = "Unknown"

        if "ratio" in self.config:
            self.ratio = self.config["ratio"]
        if "language" in self.config:
            self.language = Language(self.config["language"])
        if "subject" in self.config:
            self.subject = self.config["subject"]
        if "check_lexicon" in self.config:
            self.check_lexicon = self.config["check_lexicon"]
        if "name" in self.config:
            self.name = self.config["name"]

        for record_structure in records:
            record = Record.from_structure(record_structure)
            self.records.append(record)
            self._update_knowledge(record)

    def _update_knowledge(self, record: Record):
        last_answers: List[ResponseType] = []
        if record.question_id in self.knowledges:
            last_answers = self.knowledges[record.question_id].responses
        self.knowledges[record.question_id] = Knowledge(
            record.question_id, last_answers + [record.answer], record.time,
            record.interval)

    def register(
            self, answer: ResponseType, sentence_id: int, question_id: str,
            interval: timedelta) -> None:
        """
        Register student answer.

        :param answer: user response
        :param sentence_id: sentence identifier was used to learn the word
        :param question_id: question identifier
        :param interval: repeat interval
        """
        record: Record = Record(
            question_id, answer, sentence_id, datetime.now(), interval)
        self.records.append(record)
        self._update_knowledge(record)

    def get_next(self, skip: Set[str]) -> Optional[str]:
        """
        Get question identifier of the next question.

        :param skip: question identifiers to skip
        """
        for question_id in self.knowledges:  # type: str
            if (
                    question_id not in skip and
                    self.knowledges[question_id].is_learning() != 0 and
                    datetime.now() > self.knowledges[
                        question_id].get_next_time()):
                return question_id

    def has(self, word: str) -> bool:
        return word in self.knowledges

    def get_nearest(self) -> Optional[datetime]:
        """ Get nearest repetition time. """
        return min([
            self.knowledges[word].get_next_time() for word in self.knowledges
            if self.knowledges[word].is_learning()])

    def new_today(self):
        seen = set()
        now = datetime.now()
        today_start = datetime(year=now.year, month=now.month, day=now.day)
        count = 0
        for record in self.records:  # type: Record
            if (
                    record.question_id not in seen and
                    record.is_learning() and record.time > today_start):
                count += 1
            seen.add(record.question_id)
        return count

    def to_repeat(self):
        count = 0
        now = datetime.now()
        for word in self.knowledges:
            record: Knowledge = self.knowledges[word]
            if record.is_learning() and record.get_next_time() < now:
                count += 1
        return count

    def learning(self):
        count = 0
        for word in self.knowledges:
            record: Knowledge = self.knowledges[word]
            if record.is_learning():
                count += 1
        return count

    def write(self) -> None:
        """ Serialize learning process to a file. """
        log(f"saving learning process to {self.file_name}")
        structure = {"log": [], "config": self.config}
        for record in self.records:
            structure["log"].append(record.to_structure())
        with open(self.file_name, "w+") as output_file:
            json.dump(structure, output_file, ensure_ascii=False, indent=4)