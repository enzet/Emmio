import json
import logging
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

from emmio.dictionary.core import (
    DictionaryCollection,
    Dictionary,
    DictionaryItem,
)
from emmio.language import construct_language, ENGLISH
from emmio.lexicon.config import LexiconConfig
from emmio.lists.frequency_list import FrequencyList
from emmio.ui import get_char, Interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DATE_FORMAT: str = "%Y.%m.%d %H:%M:%S"


class LexiconResponse(Enum):
    """User response or propagation of user response."""

    UNKNOWN = 0

    KNOW = 1
    """User knows at least one meaning of the word."""

    DONT = 2
    """User doesn't know any meaning of the word."""

    KNOW_OR_NOT_A_WORD = 3
    """
    User knows at least one meaning of the word or the string is not a word.
    """

    DONT_BUT_PROPER_NOUN_TOO = 4
    """User doesn't know the word, but it is often used as a proper noun."""

    NOT_A_WORD = 5
    """
    The string is not a dictionary word.
    
    This may be misspelling, non-dictionary onomatopoeic word, foreign word,
    etc.  A frequency list may contain such words if it was not filtered using
    the dictionary.
    """

    def to_string(self) -> str:
        return self.name.lower()

    @classmethod
    def from_string(cls, string: str) -> "LexiconResponse":
        return cls[string.upper()]

    def get_message(self) -> str:
        match self:
            case self.KNOW:
                return "knows at least one meaning of the word"
            case self.DONT:
                return "does not know any meaning of the word"
            case self.KNOW_OR_NOT_A_WORD:
                return "knows or not a word"
            case self.DONT_BUT_PROPER_NOUN_TOO:
                return "does not know, but a proper noun too"
            case self.NOT_A_WORD:
                return "not a word"


class AnswerType(Enum):
    UNKNOWN = "unknown"

    USER_ANSWER = "user_answer"
    """User answer."""

    ASSUME__NOT_A_WORD__ALPHABET = "assume_not_a_word"
    """
    Assume that the word is not a dictionary word, because it contains symbols
    that are not common in the language.
    """

    ASSUME__NOT_A_WORD__DICTIONARY = "assume_not_a_word_dict"
    """
    Assume that the word is not a dictionary word, because some selected
    dictionary does not have it.
    """

    PROPAGATE__SKIP = "propagate_skip"
    """
    Previous answer was propagated because of a special flag set by the user.
    """

    PROPAGATE__NOT_A_WORD = "propagate_not_a_word"
    """
    Previous answer was propagated because it stated that the word is not a
    dictionary word.
    """

    PROPAGATE__TIME = "propagate_time"
    """Not enough time passed since last answer, therefore it was propagated."""

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class WordKnowledge:
    def __init__(self, knowing: LexiconResponse, to_skip: bool | None):
        self.knowing: LexiconResponse = knowing
        self.to_skip: bool | None = to_skip

    def to_structure(self) -> dict[str, Any]:
        """Serialize to structure."""
        structure: dict[str, Any] = {"knowing": str(self.knowing)}
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip
        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.to_structure(), ensure_ascii=False)


@dataclass
class LexiconLogRecord:
    """Record of user's answer."""

    time: datetime
    word: str
    response: LexiconResponse
    answer_type: AnswerType | None = None
    to_skip: bool | None = None

    @classmethod
    def deserialize(cls, structure: Any) -> "LexiconLogRecord":
        """Parse log record from structure."""

        if "words" in structure:
            word = random.choice(structure["words"])
        else:
            word: str = structure["word"]

        answer_type: AnswerType = AnswerType.UNKNOWN
        if "answer_type" in structure:
            answer_type = AnswerType(structure["answer_type"])

        to_skip: bool | None = None
        if "to_skip" in structure:
            to_skip = structure["to_skip"]

        return cls(
            datetime.strptime(structure["date"], DATE_FORMAT),
            word,
            LexiconResponse.from_string(structure["response"]),
            answer_type,
            to_skip,
        )

    def serialize(self) -> dict[str, Any]:
        """Serialize to structure."""

        structure: dict[str, Any] = {
            "date": self.time.strftime(DATE_FORMAT),
            "word": self.word,
            "response": self.response.to_string(),
        }
        if self.answer_type != AnswerType.UNKNOWN:
            structure["answer_type"] = self.answer_type.value
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip

        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.serialize(), ensure_ascii=False)


def rate(ratio: float) -> float | None:
    if not ratio:
        return None
    return -math.log(ratio, 2)


class WordSelection(Enum):
    ARBITRARY = "arbitrary"
    RANDOM_WORD_FROM_LIST = "random"
    FREQUENCY = "frequency"
    UNKNOWN = "unknown"
    TOP = "top"


@dataclass
class LexiconLog:
    id_: str
    selection: WordSelection
    records: list[LexiconLogRecord] = field(default_factory=list)
    frequency_list_id: str | None = None

    @classmethod
    def deserialize(cls, structure: dict[str, Any]):
        return cls(
            structure["id"],
            WordSelection(structure["selection"]),
            [LexiconLogRecord.deserialize(x) for x in structure["log"]],
            structure["frequency_list"]
            if "frequency_list" in structure
            else None,
        )

    def serialize(self) -> dict[str, Any]:
        structure: dict[str, Any] = {}
        if self.frequency_list_id is not None:
            structure["frequency_list"] = self.frequency_list_id
        structure["selection"] = self.selection.value
        structure["id"] = self.id_
        structure["log"] = []
        for record in self.records:
            structure["log"].append(record.serialize())

        return structure


class Lexicon:
    """Tracking of lexicon for one particular language through time."""

    def __init__(self, path: Path, config: LexiconConfig):
        self.language = construct_language(config.language)
        self.config: LexiconConfig = config
        self.logs: dict[str, LexiconLog] = {}

        self.file_path = path / config.file_name

        self.words: dict[str, WordKnowledge] = {}
        self.dates: list[datetime] = []
        self.responses: list[int] = []
        self.start: datetime | None = None
        self.finish: datetime | None = None

        # Read data from file.

        if not self.file_path.exists():
            self.write()

        with self.file_path.open() as input_file:
            data = json.load(input_file)

        for log_structure in data:
            self.logs[log_structure["id"]] = LexiconLog.deserialize(
                log_structure
            )

            for log_id in self.logs:
                lexicon_log: LexiconLog = self.logs[log_id]
                for record in lexicon_log.records:
                    self.words[record.word] = WordKnowledge(
                        record.response, record.to_skip
                    )

        # Fill data.

        if "log" in self.logs:
            for record in self.logs["log"].records:
                if record.response in [
                    LexiconResponse.KNOW,
                    LexiconResponse.DONT,
                ]:
                    self.dates.append(record.time)
                    self.responses.append(
                        1 if record.response == LexiconResponse.KNOW else 0
                    )

                    if self.start is None:
                        self.start = record.time
                    self.finish = record.time

    def has_log(self, log_id: str):
        return log_id in self.logs

    def add_log(self, log: LexiconLog):
        assert log.id_ not in self.logs
        self.logs[log.id_] = log

    def write(self) -> None:
        """
        Write lexicon to a JSON file using string writing. Should be faster than
        `write_json` but less accurate.
        """
        logging.debug(f"writing lexicon to {self.file_path}")

        structure: list[dict[str, Any]] = []

        for lexicon_log_id in self.logs:
            structure.append(self.logs[lexicon_log_id].serialize())

        with self.file_path.open("w+") as output:
            json.dump(structure, output, indent=4, ensure_ascii=False)

    def know(self, word: str) -> bool:
        """Check if user knows the word."""
        return self.words[word].knowing in [
            LexiconResponse.KNOW,
            LexiconResponse.DONT_BUT_PROPER_NOUN_TOO,
        ]

    def do_not_know(self, word: str) -> bool:
        """Check if user doesn't know the word."""
        return self.words[word].knowing == LexiconResponse.DONT

    def get_last_answer(
        self, word: str, log_name: str
    ) -> LexiconLogRecord | None:
        for record in reversed(self.logs[log_name].records):
            if word == record.word:
                return record

    def register(
        self,
        word: str,
        response: LexiconResponse,
        to_skip: bool | None,
        date: datetime | None = None,
        log_name: str = "log",
        answer_type: AnswerType = AnswerType.UNKNOWN,
    ) -> None:
        """
        Register user's response.

        :param word: word that user was responded to.
        :param response: response type.
        :param to_skip: skip this word in the future.
        :param date: time of response.
        :param log_name: specifier of the log.
        :param answer_type: is it was a user answer or the previous answer was
            used.
        """
        if not date:
            date = datetime.now()

        self.words[word] = WordKnowledge(response, to_skip)

        self.logs[log_name].records.append(
            LexiconLogRecord(date, word, response, answer_type, to_skip)
        )

        if response in [LexiconResponse.KNOW, LexiconResponse.DONT]:
            self.dates.append(date)
            self.responses.append(1 if response == LexiconResponse.KNOW else 0)

            if not self.start or date < self.start:
                self.start = date
            if not self.finish or date > self.finish:
                self.finish = date

    def get_statistics(self) -> float:
        count: list[int] = [0, 0]
        for record in self.logs["log"].records:
            if record.response == LexiconResponse.KNOW:
                count[0] += 1
            elif record.response == LexiconResponse.DONT:
                count[1] += 1

        count_ratio: float = 0
        if count[0] + count[1]:
            count_ratio = count[0] / (count[0] + count[1])

        return count_ratio

    def has(self, word: str) -> bool:
        """Check whether there is a response in at least one log."""
        return word in self.words

    def get(self, word: str) -> LexiconResponse:
        """Get the most recent response from all logs."""
        return self.words[word].knowing

    def get_log_size(self, log_name: str) -> int:
        responses = [x.response for x in self.logs[log_name].records]
        return responses.count(LexiconResponse.DONT) + responses.count(
            LexiconResponse.KNOW
        )

    def count_unknowns(
        self, log_name: str, point_1: datetime = None, point_2: datetime = None
    ) -> int:
        """Return the number of UNKNOWN answers."""
        records: Iterator[LexiconLogRecord] = filter(
            lambda record: not point_1 or point_1 <= record.time <= point_2,
            self.logs[log_name].records,
        )
        return [x.response for x in records].count(LexiconResponse.DONT)

    def get_bounds(
        self, point_1: datetime, point_2: datetime
    ) -> tuple[int, int]:
        min_value, max_value, min_index, max_index = None, None, None, None

        for i in range(len(self.dates)):
            if point_1 <= self.dates[i] <= point_2:
                if not min_index or self.dates[i] < min_value:
                    min_value = self.dates[i]
                    min_index = i
                if not max_index or self.dates[i] > max_value:
                    max_value = self.dates[i]
                    max_index = i

        return min_index, max_index

    def get_average(
        self, index_1: int | None = None, index_2: int | None = None
    ) -> float | None:
        """
        Get average ratio.

        :param index_1: start index.
        :param index_2: finish index.
        :return: average ratio or None if ratio is infinite.
        """
        if not index_1 and not index_2:
            if len(self.responses) == 0:
                return None
            else:
                return 1 - (sum(self.responses) / len(self.responses))

        return 1 - (
            sum(self.responses[index_1:index_2])
            / len(self.responses[index_1:index_2])
        )

    def get_preferred_interval(self) -> int:
        return int(100 / self.get_average())

    def construct_precise(
        self, precision: int = 100
    ) -> (list[datetime], list[float]):
        dates: list[datetime] = []
        rates: list[float] = []
        left, right, knowns = 0, 0, 0

        while right < len(self.dates) - 1:
            knowns += 1 if self.responses[right] else 0
            right += 1
            length: int = right - left

            if length - knowns > precision:
                knowns -= 1 if self.responses[left] else 0
                left += 1
                length: int = right - left

            if length - knowns >= precision:
                dates.append(self.dates[right])
                rates.append(
                    rate((length - knowns) / length if length else 0.0)
                )

        return dates, rates

    def get_last_rate(self, precision: int = 100) -> float | None:
        dates, rates = self.construct_precise(precision)
        if rates:
            return rates[-1]
        return None

    def get_last_rate_number(self, precision: int = 100) -> float:
        value: float | None = self.get_last_rate(precision)
        if value is None:
            return 0
        return value

    def construct_by_frequency(self, frequency_list: FrequencyList):
        response = None
        knowns: int = 0
        unknowns: int = 0
        for word in frequency_list.get_words():
            if self.has(word):
                response = self.get(word)
            if response == LexiconResponse.KNOW:
                knowns += frequency_list.get_occurrences(word)
            elif response == LexiconResponse.DONT:
                unknowns += frequency_list.get_occurrences(word)

    def get_rate(
        self, point_1: datetime, point_2: datetime
    ) -> (float | None, float | None):
        """
        Get rate for selected time interval.

        :param point_1: start point in time.
        :param point_2: finish point in time.
        :return: None if there is no enough data to compute rate.
        """
        preferred_interval: int = self.get_preferred_interval()

        index_1, index_2 = self.get_bounds(point_1, point_2)

        if index_1 and index_2 and index_2 - index_1 >= preferred_interval:
            return rate(self.get_average(index_1, index_2)), 1.0
        elif index_2 and index_2 >= preferred_interval:
            return (
                rate(self.get_average(index_2 - preferred_interval, index_2)),
                (index_2 - index_1) / preferred_interval,
            )
        elif index_2:
            return None, (index_2 - index_1) / preferred_interval

        return None, None

    def get_top_unknown(self, frequency_list: FrequencyList) -> list[str]:
        """
        Get all words user marked as unknown in order of frequency.

        :param frequency_list: sort words using this list.
        """
        result: list[str] = []

        for word in sorted(
            self.words.keys(), key=lambda x: -frequency_list.get_occurrences(x)
        ):
            word_knowledge = self.words[word]
            if word_knowledge.knowing == LexiconResponse.DONT:
                result.append(word)

        return result

    def ask(
        self,
        interface: Interface,
        word: str,
        word_list: list[str],
        dictionaries: DictionaryCollection,
        skip_known: bool = False,
        skip_unknown: bool = False,
        log_name: str = "log",
    ) -> (bool, LexiconResponse, Dictionary | None):
        """Ask user if the word is known."""
        sys.stdout.write(f"\n    {word}\n")

        if word_list:
            if word + "\n" in word_list:
                sys.stdout.write("In word list.")
            else:
                sys.stdout.write("Not in word list.")
            if word[0].upper() + word[1:] + "\n" in word_list:
                sys.stdout.write("Capitalized in word list.")
            else:
                sys.stdout.write("Capitalized not in word list.")

        if self.has(word):
            print("Last response was: " + self.get(word).get_message() + ".")

        items: list[DictionaryItem] = dictionaries.get_items(
            word, self.language
        )
        if items:
            print("[Show translation]")
            get_char()
            print(
                "\n".join(map(lambda x: x.to_str([ENGLISH], interface), items))
            )

        print("Do you know at least one meaning of this word? [Y/n/b/s/-/q]> ")

        answer: str = get_char()
        while answer not in "yY\rnNbBsS-qQz":
            answer = get_char()

        response: LexiconResponse
        skip_in_future: bool | None = None

        if answer in "yY\r":
            response = LexiconResponse.KNOW
        elif answer in "nN":
            response = LexiconResponse.DONT
        elif answer in "bB":
            response = LexiconResponse.DONT_BUT_PROPER_NOUN_TOO
        elif answer in "sS":
            response = LexiconResponse.KNOW
            skip_in_future = True
        elif answer == "-":
            response = LexiconResponse.NOT_A_WORD
        elif answer in "qQ":
            print("Quit.")
            self.write()
            return False, None, None
        else:
            response = LexiconResponse.DONT

        print(response.get_message())

        if skip_in_future is None:
            if response == LexiconResponse.KNOW:
                skip_in_future = skip_known
            elif response == LexiconResponse.DONT:
                skip_in_future = skip_unknown

        self.register(
            word,
            response,
            skip_in_future,
            log_name=log_name,
            answer_type=AnswerType.USER_ANSWER,
        )

        return skip_in_future, response, None

    def binary_search(
        self,
        interface: Interface,
        frequency_list: FrequencyList,
        dictionaries: DictionaryCollection,
    ) -> None:
        left_border, right_border = 0, int((len(frequency_list) - 1) / 2)
        while True:
            print(left_border, right_border)
            index: int = int((left_border + right_border) / 2)
            picked_word, occurrences = frequency_list.get_word_by_index(index)
            print(occurrences)
            to_skip, response, dictionary = self.ask(
                interface,
                picked_word,
                [],
                dictionaries,
                log_name="log_binary_search",
            )
            if not response:
                break
            if response == LexiconResponse.KNOW:
                left_border = index
            elif response == LexiconResponse.DONT:
                right_border = index
            else:
                left_border += 2
            dont = 0
            print(f"index: {index}, len: {len(frequency_list)}")
            for i in range(index, len(frequency_list) - 1):
                _, occurrences = frequency_list.get_word_by_index(i)
                dont += occurrences
            print(f"dont: {dont}, all: {frequency_list.get_all_occurrences()}")
            print(f"Rate: {rate(dont / frequency_list.get_all_occurrences())}")
            self.write()

    def check(
        self,
        interface: Interface,
        frequency_list: FrequencyList,
        stop_at: int | None,
        dictionaries: DictionaryCollection,
        log_type: str,
        skip_known: bool,
        skip_unknown: bool,
        stop_at_wrong: int | None,
        word_list: list[str] = None,
        learning=None,
    ) -> str:
        """
        Check current user vocabulary.

        :param interface: interface for communicating with the user.
        :param frequency_list: list of the words with frequency to check.
        :param stop_at: stop after a number of actions.
        :param dictionaries: offer a translation from one of dictionaries.
        :param log_type: the method of picking words.
        :param skip_known: skip this word in the future if it is known.
        :param skip_unknown: skip this word in the future if it is unknown.
        :param stop_at_wrong: stop after a number of unknown words.

        :return: exit code.
        """

        # Actions during current session:
        actions: int = 0
        wrong_answers: int = 0

        log_name: str
        if log_type == "frequency":
            log_name = "log"
        elif log_type == "random":
            log_name = "log_random"
        elif log_type == "most frequent":
            log_name = "log_top"
        else:
            print("ERROR: unknown log type")
            return "error"

        exit_code: str = "quit"

        mf_index: int = 0

        while True:
            picked_word = None
            if log_type == "frequency":
                (
                    picked_word,
                    occurrences,
                ) = frequency_list.get_random_word_by_frequency()
            elif log_type == "random":
                picked_word, occurrences = frequency_list.get_random_word()
            elif log_type == "most frequent":
                picked_word, occurrences = frequency_list.get_word_by_index(
                    mf_index
                )
                mf_index += 1
                if self.has(picked_word) or learning.has(picked_word):
                    continue
                items: list[DictionaryItem] = dictionaries.get_items(
                    picked_word
                )
                if not items or items[0].is_not_common(learning.language):
                    continue
                print(f"[{mf_index}]")

            if self.do_skip(picked_word, skip_known, skip_unknown, log_name):
                continue

            to_skip, response, dictionary = self.ask(
                interface,
                picked_word,
                word_list,
                dictionaries,
                skip_known,
                skip_unknown,
                log_name=log_name,
            )
            actions += 1
            if response == LexiconResponse.DONT:
                wrong_answers += 1
            # self.write()

            average: float | None = self.get_average()

            precision: float = self.count_unknowns(log_name) / 100
            rate_string = f"{rate(average):.2f}" if rate(average) else "unknown"
            if precision < 1:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Rate so far is: {rate_string}")
            else:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Current rate is: {self.get_last_rate_number():.2f}")
            print(f"Words: {len(self.words):d}")

            if not response:
                exit_code = "quit"
                break

            if stop_at and actions >= stop_at:
                exit_code = "limit"
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                exit_code = "limit"
                break

        self.write()

        return exit_code

    def do_skip(
        self,
        picked_word: str,
        skip_known: bool,
        skip_unknown: bool,
        log_name: str,
    ) -> bool:
        last_response: LexiconResponse | None = None
        if self.has(picked_word):
            last_response = self.get(picked_word)

        if last_response is not None:
            if (
                self.words[picked_word].to_skip
                or skip_known
                and last_response == LexiconResponse.KNOW
                or skip_unknown
                and last_response == LexiconResponse.DONT
            ):
                print("[propagate.skip] " + picked_word)
                to_skip: bool = self.words[picked_word].to_skip
                self.register(
                    picked_word,
                    last_response,
                    to_skip,
                    log_name=log_name,
                    answer_type=AnswerType.PROPAGATE__SKIP,
                )
                return True

            if last_response == LexiconResponse.NOT_A_WORD:
                print("[propagate.not_a_word] " + picked_word)
                self.register(
                    picked_word,
                    LexiconResponse.NOT_A_WORD,
                    None,
                    log_name=log_name,
                    answer_type=AnswerType.PROPAGATE__NOT_A_WORD,
                )
                return True

            was_answered_recently: bool = False

            for record in reversed(self.logs[log_name].records):
                delta = record.time - datetime.now()
                if delta.days > 30:
                    break
                if (
                    picked_word == record.word
                    and record.answer_type == AnswerType.USER_ANSWER
                ):
                    was_answered_recently = True
                    break

            if was_answered_recently:
                print("[propagate.time] " + picked_word)
                self.register(
                    picked_word,
                    last_response,
                    None,
                    log_name=log_name,
                    answer_type=AnswerType.PROPAGATE__TIME,
                )
                return True

        # Mark word as "not a word" if it contains symbols that do not appear
        # in language.

        is_foreign: bool = False
        if self.language.get_symbols():
            for symbol in picked_word:
                if symbol not in self.language.get_symbols():
                    is_foreign = True
                    break

        if is_foreign:
            print("[assume.not_a_word] " + picked_word)
            self.register(
                picked_word,
                LexiconResponse.NOT_A_WORD,
                None,
                log_name=log_name,
                answer_type=AnswerType.ASSUME__NOT_A_WORD__ALPHABET,
            )
            return True

        return False

    def print_statistics(self, log_name: str) -> None:
        count_ratio: float = self.get_statistics()

        print(
            "Skipping:          %9.4f"
            % (len(self.logs["log"].records) / len(self.words))
        )
        print("Count ratio:       %9.4f %%" % (count_ratio * 100))
        print("Words:             %4d" % len(self.words))
        print("Size:              %4d" % self.get_log_size(log_name))

    def __len__(self) -> int:
        return len(self.words)

    def __repr__(self) -> str:
        return f"<User lexicon {self.language.get_name()}>"
