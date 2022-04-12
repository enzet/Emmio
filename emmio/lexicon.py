import json
import math
import os
from datetime import datetime
from enum import Enum
from typing import Any, Iterator, Optional

from emmio.dictionary import Dictionaries, Dictionary, DictionaryItem
from emmio.frequency import FrequencyList
from emmio.language import Language
from emmio.ui import get_char, log, one_button, write, Interface

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DATE_FORMAT: str = "%Y.%m.%d %H:%M:%S"


class LexiconResponse(Enum):
    KNOW = "know"
    DO_NOT_KNOW = "dont"
    KNOW_OR_NOT_A_WORD = "know_or_not_a_word"
    DO_NOT_BUT_PROPER_NOUN_TOO = "dont_but_proper_noun_too"
    NOT_A_WORD = "not_a_word"

    def get_message(self) -> str:
        if self == self.KNOW:
            return "knows at least one meaning of the word"
        if self == self.DO_NOT_KNOW:
            return "does not know any meaning of the word"
        if self == self.KNOW_OR_NOT_A_WORD:
            return "knows or not a word"
        if self == self.DO_NOT_BUT_PROPER_NOUN_TOO:
            return "does not know, but a proper noun too"
        if self == self.NOT_A_WORD:
            return "not a word"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class AnswerType(Enum):
    UNKNOWN = "unknown"

    # First answer.
    USER_ANSWER = "user_answer"
    ASSUME__NOT_A_WORD__ALPHABET = "assume_not_a_word"
    ASSUME__NOT_A_WORD__DICTIONARY = "assume_not_a_word_dict"

    # Propagation of a previous answer.
    PROPAGATE__SKIP = "propagate_skip"
    PROPAGATE__NOT_A_WORD = "propagate_not_a_word"
    PROPAGATE__TIME = "propagate_time"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class WordKnowledge:
    def __init__(self, knowing: LexiconResponse, to_skip: Optional[bool]):
        self.knowing: LexiconResponse = knowing
        self.to_skip: Optional[bool] = to_skip

    def to_structure(self) -> dict[str, Any]:
        """Serialize to structure."""
        structure: dict[str, Any] = {"knowing": str(self.knowing)}
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip
        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.to_structure(), ensure_ascii=False)


class LogRecord:
    """
    Record of user's answer.
    """
    def __init__(
            self, date: datetime, words: list[str],
            response: LexiconResponse,
            answer_type: AnswerType = AnswerType.UNKNOWN,
            to_skip: Optional[bool] = None):
        """
        :param date: time of the answer.
        :param words: list of words under question.
        :param response: the result.
        :param answer_type: is it was a user answer or the previous answer was
            used.
        :param to_skip: skip this word in the future
        """
        self.date: datetime = date
        self.words: list[str] = words
        self.response: LexiconResponse = response
        self.answer_type: AnswerType = answer_type
        self.to_skip: Optional[bool] = to_skip

        # FIXME: remove when all lexicons are updated
        if self.answer_type == AnswerType.PROPAGATE__SKIP:
            self.to_skip = True

    @classmethod
    def from_structure(cls, structure: Any) -> "LogRecord":
        """
        Parse log record from structure.
        """
        if isinstance(structure, list):
            date_string, word, response = structure  # type: (str, str, str)
            date = datetime.strptime(date_string, DATE_FORMAT)
            return cls(date, [word], LexiconResponse(response))
        elif isinstance(structure, dict):
            answer_type: AnswerType = AnswerType.UNKNOWN
            if "answer_type" in structure:
                answer_type = AnswerType(structure["answer_type"])
            to_skip: Optional[bool] = None
            if "to_skip" in structure:
                to_skip = structure["to_skip"]
            if "word" in structure:
                words = [structure["word"]]
            else:  # "words" in structure
                words = structure["words"]
            return cls(
                datetime.strptime(structure["date"], DATE_FORMAT),
                words, LexiconResponse(structure["response"]), answer_type,
                to_skip)

    def to_structure(self) -> dict[str, Any]:
        """
        Serialize to structure.
        """
        structure = {"date": self.date.strftime(DATE_FORMAT)}
        if len(self.words) == 1:
            structure["word"] = self.words[0]
        else:
            structure["words"] = self.words
        structure["response"] = self.response.value
        if self.answer_type != AnswerType.UNKNOWN:
            structure["answer_type"] = self.answer_type.value
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip

        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.to_structure(), ensure_ascii=False)


def rate(ratio: float) -> Optional[float]:
    if not ratio:
        return None
    return -math.log(ratio, 2)


class LexiconLog:
    def __init__(self, structure: dict[str, Any]):
        self.id_: str = structure["id"]

        self.frequency_list_id: Optional[str]
        if "frequency_list" in structure:
            self.frequency_list_id = structure["frequency_list"]
        else:
            self.frequency_list_id = None

        self.selection: str = structure["selection"]

        self.records: list[LogRecord] = []
        for record_structure in structure["log"]:  # type: dict[str, str]
            self.records.append(LogRecord.from_structure(record_structure))

    def to_structure(self) -> dict[str, Any]:
        structure: dict[str, Any] = {}
        if self.frequency_list_id is not None:
            structure["frequency_list"] = self.frequency_list_id
        structure["selection"] = self.selection
        structure["id"] = self.id_
        structure["log"] = []
        for record in self.records:
            structure["log"].append(record.to_structure())

        return structure


class Lexicon:
    """
    Tracking of lexicon for one particular language through time.
    """
    def __init__(self, language: Language, file_name: str):

        self.language: Language = language
        self.file_name: str = file_name

        self.words: dict[str, WordKnowledge] = {}
        self.logs: dict[str, LexiconLog] = {}

        # Temporary data.

        self.dates: list[datetime] = []
        self.responses: list[int] = []
        self.start: Optional[datetime] = None
        self.finish: Optional[datetime] = None

        # Read data from file.

        log(f"reading lexicon from {self.file_name}")

        if not os.path.isfile(self.file_name):
            return

        with open(self.file_name) as input_file:
            data = json.load(input_file)

        for log_structure in data:  # type: dict[str, Any]
            self.logs[log_structure["id"]] = LexiconLog(log_structure)

            for log_id in self.logs:
                lexicon_log: LexiconLog = self.logs[log_id]
                for record in lexicon_log.records:  # type: LogRecord
                    for word in record.words:
                        self.words[word] = WordKnowledge(
                            record.response, record.to_skip)

        # Fill data.

        for record in self.logs["log"].records:  # type: LogRecord
            if record.response in [
                    LexiconResponse.KNOW, LexiconResponse.DO_NOT_KNOW]:
                self.dates.append(record.date)
                self.responses.append(
                    1 if record.response == LexiconResponse.KNOW else 0)

                if self.start is None:
                    self.start = record.date
                self.finish = record.date

    def write(self) -> None:
        """
        Write lexicon to a JSON file using string writing. Should be faster than
        `write_json` but less accurate.
        """
        log(f"writing lexicon to {self.file_name}")

        structure: list[dict[str, Any]] = []

        for lexicon_log_id in self.logs:
            structure.append(self.logs[lexicon_log_id].to_structure())

        with open(self.file_name, "w+") as output:
            json.dump(structure, output, indent=4, ensure_ascii=False)

    def know(self, word: str) -> bool:
        """
        Check if user knows the word.
        """
        return self.words[word].knowing in [
            LexiconResponse.KNOW, LexiconResponse.DO_NOT_BUT_PROPER_NOUN_TOO]

    def do_not_know(self, word: str) -> bool:
        """
        Check if user doesn't know the word.
        """
        return self.words[word].knowing == LexiconResponse.DO_NOT_KNOW

    def get_last_answer(self, word: str, log_name: str) -> Optional[LogRecord]:
        for record in reversed(self.logs[log_name].records):  # type: LogRecord
            if word in record.words:
                return record

    def register(
            self, words: list[str], response: LexiconResponse,
            to_skip: Optional[bool], date: Optional[datetime] = None,
            log_name: str = "log",
            answer_type: AnswerType = AnswerType.UNKNOWN) -> None:
        """
        Register user's response.

        :param words: list of words that user was responded to.
        :param response: response type.
        :param to_skip: skip this word in the future.
        :param date: time of response.
        :param log_name: specifier of the log.
        :param answer_type: is it was a user answer or the previous answer was
            used.
        """
        if not date:
            date = datetime.now()

        for word in words:
            self.words[word] = WordKnowledge(response, to_skip)

        if log_name not in self.logs:
            self.logs[log_name] = LexiconLog()
        self.logs[log_name].records.append(
            LogRecord(date, words, response, answer_type))

        if response in [LexiconResponse.KNOW, LexiconResponse.DO_NOT_KNOW]:
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
            elif record.response == LexiconResponse.DO_NOT_KNOW:
                count[1] += 1

        count_ratio: float = 0
        if count[0] + count[1]:
            count_ratio = count[0] / (count[0] + count[1])

        return count_ratio

    def has(self, word: str) -> bool:
        return word in self.words

    def get(self, word: str) -> LexiconResponse:
        return self.words[word].knowing

    def get_log_size(self, log_name: str) -> int:
        responses = [x.response for x in self.logs[log_name].records]
        return (
            responses.count(LexiconResponse.DO_NOT_KNOW) +
            responses.count(LexiconResponse.KNOW))

    def count_unknowns(
            self, log_name: str, point_1: datetime = None,
            point_2: datetime = None) -> int:
        """
        Return the number of UNKNOWN answers.
        """
        records: Iterator[LogRecord] = filter(
            lambda record: not point_1 or point_1 <= record.date <= point_2,
            self.logs[log_name].records)
        return [x.response for x in records].count(
            LexiconResponse.DO_NOT_KNOW)

    def get_bounds(self, point_1: datetime, point_2: datetime) -> (int, int):

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
            self, index_1: Optional[int] = None,
            index_2: Optional[int] = None) -> Optional[float]:
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

        return 1 - (sum(self.responses[index_1:index_2]) /
                    len(self.responses[index_1:index_2]))

    def get_data(self, start: datetime, finish: datetime) -> (int, int):
        length: int = 0
        data: int = 0
        for index in range(len(self.dates)):  # type: int
            if start <= self.dates[index] < finish:
                length += 1
                data += self.responses[index]
        return length, data

    def get_preferred_interval(self) -> int:
        return int(100 / self.get_average())

    def construct_precise(
            self, precision: int = 100) -> (list[datetime], list[float]):

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
                    rate((length - knowns) / length if length else 0.0))

        return dates, rates

    def get_last_rate(self, precision: int = 100) -> float:
        dates, rates = self.construct_precise(precision)
        if rates:
            return rates[-1]
        return 0

    def construct_by_frequency(self, frequency_list: FrequencyList):
        response = None
        knowns: int = 0
        unknowns: int = 0
        for word in frequency_list.get_words():
            if self.has(word):
                response = self.get(word)
            if response == LexiconResponse.KNOW:
                knowns += frequency_list.get_occurrences(word)
            elif response == LexiconResponse.DO_NOT_KNOW:
                unknowns += frequency_list.get_occurrences(word)

    def get_rate(
            self, point_1: datetime, point_2: datetime) -> (
            Optional[float], Optional[float]):
        """
        Get rate for selected time interval.

        :param point_1: start point in time.
        :param point_2: finish point in time.
        :return: None if there is no enough data to compute rate.
        """
        preferred_interval = self.get_preferred_interval()

        index_1, index_2 = self.get_bounds(point_1, point_2)

        if index_1 and index_2 and index_2 - index_1 >= preferred_interval:
            return rate(self.get_average(index_1, index_2)), 1.0
        elif index_2 and index_2 >= preferred_interval:
            return (
                rate(self.get_average(index_2 - preferred_interval, index_2)),
                (index_2 - index_1) / preferred_interval)
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
                self.words.keys(),
                key=lambda x: -frequency_list.get_occurrences(x)):

            word_knowledge = self.words[word]
            if word_knowledge.knowing == LexiconResponse.DO_NOT_KNOW:
                result.append(word)

        return result

    def ask(
            self, interface: Interface, word: str, word_list: list[str],
            dictionaries: list[Dictionary], skip_known: bool = False,
            skip_unknown: bool = False, log_name: str = "log") -> (
            bool, LexiconResponse, Optional[Dictionary]):
        """
        Ask user if the word is known.
        """
        write(f"\n    {word}\n")

        if word_list:
            if word + "\n" in word_list:
                write("In word list.", color="green")
            else:
                write("Not in word list.", color="red")
            if word[0].upper() + word[1:] + "\n" in word_list:
                write("Capitalized in word list.", color="green")
            else:
                write("Capitalized not in word list.", color="red")

        if self.has(word):
            print("Last response was: " + self.get(word).get_message() + ".")

        items: list[DictionaryItem] = Dictionaries(dictionaries).get_items(word)

        if items:
            one_button("Show translation")
            print("\n".join(map(lambda x: x.to_str("ru", interface), items)))

        print("Do you know at least one meaning of this word? [Y/n/b/s/-/q]> ")
        answer = get_char()
        while answer not in [
                "y", "Y", "\r", "n", "N", "b", "B", "s", "S", "-", "q", "Q",
                "z"]:
            answer = get_char()

        response: LexiconResponse
        skip_in_future: Optional[bool] = None

        if answer in ["y", "Y", "\r"]:
            response = LexiconResponse.KNOW
        elif answer in ["n", "N"]:
            response = LexiconResponse.DO_NOT_KNOW
        elif answer in ["b", "B"]:
            response = LexiconResponse.DO_NOT_BUT_PROPER_NOUN_TOO
        elif answer in ["s", "S"]:
            response = LexiconResponse.KNOW
            skip_in_future = True
        elif answer == "-":
            response = LexiconResponse.NOT_A_WORD
        elif answer in ["q", "Q"]:
            print("Quit.")
            self.write()
            return False, None, None
        else:
            response = LexiconResponse.DO_NOT_KNOW

        print(response.get_message())

        if skip_in_future is None:
            if response == LexiconResponse.KNOW:
                skip_in_future = skip_known
            elif response == LexiconResponse.DO_NOT_KNOW:
                skip_in_future = skip_unknown

        self.register(
            [word], response, skip_in_future, log_name=log_name,
            answer_type=AnswerType.USER_ANSWER)

        return skip_in_future, response, None

    def binary_search(
        self,
        interface: Interface,
        frequency_list: FrequencyList,
        dictionaries: list[Dictionary],
    ):
        left_border, right_border = 0, int((len(frequency_list) - 1) / 2)
        while True:
            print(left_border, right_border)
            index: int = int((left_border + right_border) / 2)
            picked_word, occurrences = (
                frequency_list.get_word_by_index(index))
            print(occurrences)
            to_skip, response, dictionary = self.ask(
                interface,
                picked_word,
                [],
                dictionaries,
                log_name="log_binary_search"
            )
            if not response:
                break
            if response == LexiconResponse.KNOW:
                left_border = index
            elif response == LexiconResponse.DO_NOT_KNOW:
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
            self, interface: Interface,
            frequency_list: FrequencyList, stop_at: Optional[int],
            dictionaries: list[Dictionary], log_type: str,
            skip_known: bool, skip_unknown: bool,
            stop_at_wrong: Optional[int],
            word_list: list[str] = None) -> str:
        """
        Check current user vocabulary.

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
        else:
            print("ERROR: unknown log type")
            return "error"

        if log_name not in self.logs:
            self.logs[log_name] = []

        exit_code: str = "quit"

        while True:
            picked_word = None
            if log_type == "frequency":
                picked_word, occurrences = (
                    frequency_list.get_random_word_by_frequency())
            elif log_type == "random":
                picked_word, occurrences = frequency_list.get_random_word()

            if self.do_skip(picked_word, skip_known, skip_unknown, log_name):
                continue

            to_skip, response, dictionary = self.ask(
                interface, picked_word, word_list, dictionaries, skip_known,
                skip_unknown, log_name=log_name)
            actions += 1
            if response == LexiconResponse.DO_NOT_KNOW:
                wrong_answers += 1
            # self.write()

            average: Optional[float] = self.get_average()

            precision: float = self.count_unknowns(log_name) / 100
            rate_string = f"{rate(average):.2f}" if rate(average) else "unknown"
            if precision < 1:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Rate so far is: {rate_string}")
            else:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Rate is: {rate_string}")
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
            self, picked_word: str, skip_known: bool, skip_unknown: bool,
            log_name: str) -> bool:

        last_record: LogRecord = self.get_last_answer(picked_word, log_name)

        if last_record is not None:
            if (self.words[picked_word].to_skip or
                    (skip_known and
                     self.get(picked_word) == LexiconResponse.KNOW) or
                    (skip_unknown and
                     self.get(picked_word) == LexiconResponse.DO_NOT_KNOW)):

                answer_type = AnswerType.PROPAGATE__SKIP

                print("[propagate.skip] " + picked_word)

                response: LexiconResponse = self.get(picked_word)
                to_skip: bool = self.words[picked_word].to_skip
                self.register(
                    [picked_word], response, to_skip, log_name=log_name,
                    answer_type=answer_type)
                return True

            if self.get(picked_word) == LexiconResponse.NOT_A_WORD:
                answer_type = AnswerType.PROPAGATE__NOT_A_WORD
                self.register(
                    [picked_word], LexiconResponse.NOT_A_WORD, None,
                    log_name=log_name, answer_type=answer_type)
                return True

            was_user_answer: bool = False

            for record in reversed(self.logs[log_name].records):  # type: LogRecord
                delta = record.date - datetime.now()
                if delta.days > 30:
                    break
                if picked_word in record.words and \
                        record.answer_type == AnswerType.USER_ANSWER:
                    was_user_answer = True
                    break

            if was_user_answer:
                print("[propagate.time] " + picked_word)
                self.register(
                    [picked_word], last_record.response, None,
                    log_name=log_name,
                    answer_type=AnswerType.PROPAGATE__TIME)
                return True

        # Mark word as "not a word" if it contains symbols that do not appear
        # in language.

        foreign = False
        if self.language.get_symbols():
            for symbol in picked_word:
                if symbol not in self.language.get_symbols():
                    foreign = True
                    break

        if foreign:
            print("[assume.not_a_word] " + picked_word)
            self.register(
                [picked_word], LexiconResponse.NOT_A_WORD, None,
                log_name=log_name,
                answer_type=AnswerType.ASSUME__NOT_A_WORD__ALPHABET)
            return True

        return False

    def print_statistics(self, log_name: str) -> None:
        count_ratio: float = self.get_statistics()

        print("Skipping:          %9.4f" %
              (len(self.logs["log"].records) / len(self.words)))
        print("Count ratio:       %9.4f %%" % (count_ratio * 100))
        print("Words:             %4d" % len(self.words))
        print("Size:              %4d" % self.get_log_size(log_name))

    def __len__(self) -> int:
        return len(self.words)

    def __repr__(self) -> str:
        return f"<User lexicon {self.language.get_name()}>"
