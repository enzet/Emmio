import json
import math
import os
import re

from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TextIO

from emmio.ui import get_char, one_button, write
from emmio.dictionary import Dictionary
from emmio.frequency import FrequencyList
from emmio.language import symbols


class LexiconResponse(Enum):
    KNOW = "know"
    DO_NOT_KNOW = "dont"
    KNOW_OR_NOT_A_WORD = "know_or_not_a_word"
    DO_NOT_BUT_PROPER_NOUN_TOO = "dont_but_proper_noun_too"
    NOT_A_WORD = "not_a_word"

    def get_message(self) -> str:
        if self == self.KNOW:
            return "know"
        if self == self.DO_NOT_KNOW:
            return "don't know"
        if self == self.KNOW_OR_NOT_A_WORD:
            return "know or not a word"
        if self == self.DO_NOT_BUT_PROPER_NOUN_TOO:
            return "don't know but proper noun too"
        if self == self.NOT_A_WORD:
            return "not a word"

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


class WordKnowledge:
    def __init__(self, knowing: LexiconResponse, to_skip: Optional[bool]):
        self.knowing: LexiconResponse = knowing
        self.to_skip: Optional[bool] = to_skip

    def to_structure(self) -> Dict[str, Any]:
        """
        Serialize to structure.
        """
        structure: Dict[str, Any] = {"knowing": str(self.knowing)}
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip
        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.to_structure(), ensure_ascii=False)


class LogRecord:
    """
    Record of user's answer.
    """
    def __init__(self, date: datetime, words: List[str],
            response: LexiconResponse, is_reused: Optional[bool] = None):
        """
        :param date: time of the answer.
        :param words: list of words under question.
        :param response: the result.
        :param is_reused: if the previous answer was used, `None` if it is
            unknown.
        """
        self.date: datetime = date
        self.words: List[str] = words
        self.response: LexiconResponse = response
        self.is_reused: Optional[bool] = is_reused

    @classmethod
    def from_structure(cls, structure) -> "LogRecord":
        if isinstance(structure, list):
            date_string, word, response = structure  # type: (str, str, str)
            date = datetime.strptime(date_string, "%Y.%m.%d %H:%M:%S")
            return cls(date, [word], LexiconResponse(response))
        elif isinstance(structure, dict):
            is_reused = None
            if "is_reused" in structure:
                is_reused = structure["is_reused"]
            if "word" in structure:
                words = [structure["word"]]
            else:  # "words" in structure
                words = structure["words"]
            return cls(
                datetime.strptime(structure["date"], "%Y.%m.%d %H:%M:%S"),
                words, LexiconResponse(structure["response"]),
                is_reused)

    def to_structure(self) -> Dict[str, Any]:
        """
        Serialize to structure.
        """
        structure = {"date": self.date.strftime("%Y.%m.%d %H:%M:%S")}
        if len(self.words) == 1:
            structure["word"] = self.words[0]
        else:
            structure["words"] = self.words
        structure["response"] = self.response.value
        if self.is_reused is not None:
            structure["is_reused"] = self.is_reused

        return structure

    def to_json_str(self) -> str:
        return json.dumps(self.to_structure(), ensure_ascii=False)


def rate(ratio: float) -> Optional[float]:
    if not ratio:
        return None
    return -math.log(ratio, 2)


class Lexicon:
    """
    Tracking of lexicon for one particular language through time.
    """
    def __init__(self, language: str, file_name: str):

        self.language: str = language
        self.file_name: str = file_name

        self.words: Dict[str, WordKnowledge] = {}
        self.logs: Dict[str, List[LogRecord]] = {}

        # Temporary data.

        self.dates: List[datetime] = []
        self.responses: List[int] = []
        self.start: Optional[datetime] = None
        self.finish: Optional[datetime] = None

    def rd(self, data):
        for word in data["words"]:
            record = data["words"][word]
            if isinstance(record, list):
                self.words[word] = WordKnowledge(record[1], None)
            elif isinstance(record, dict):
                to_skip = None
                if "to_skip" in record:
                    to_skip = record["to_skip"]
                self.words[word] = WordKnowledge(
                    LexiconResponse(record["knowing"]), to_skip)

        for key in data:  # type: str
            if key.startswith("log"):
                self.logs[key]: List[LogRecord] = []
                for structure in data[key]:
                    self.logs[key].append(LogRecord.from_structure(structure))

    def read(self):
        write("Reading lexicon from " + self.file_name + "...")
        with open(self.file_name, "r") as input_file:
            self.rd(json.load(input_file))
        self.fill()

    def fill(self):
        if "log" not in self.logs:
            return
        for record in self.logs["log"]:  # type: LogRecord
            if record.response in [LexiconResponse.KNOW,
                    LexiconResponse.DO_NOT_KNOW]:
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
        words_structure = {}
        for word in self.words:
            words_structure[word] = self.words[word].to_structure()

        with open(self.file_name, "w+") as output:
            output.write("{\n")

            for key in sorted(self.logs):  # type: str
                log: List[LogRecord] = self.logs[key]
                output.write('    "' + key + '": [\n')
                log_length = len(log)
                for index, record in enumerate(log):  # type: int, LogRecord
                    output.write('        ' + record.to_json_str())
                    output.write("\n" if index == log_length - 1 else ",\n")
                output.write("    ],\n")

            output.write('    "words": {\n')
            words_length = len(self.words)
            for index, word in enumerate(self.words):  # type: int, str
                output.write('        "' + word + '": ' +
                    self.words[word].to_json_str())
                output.write("\n" if index == words_length - 1 else ",\n")
            output.write("    }\n")

            output.write("}\n")

    def know(self, word: str) -> bool:
        """
        Check if user knows the word.
        """
        return self.words[word].knowing in \
            [LexiconResponse.KNOW, LexiconResponse.DO_NOT_BUT_PROPER_NOUN_TOO]

    def do_not_know(self, word: str) -> bool:
        """
        Check if user doesn't know the word.
        """
        return self.words[word].knowing == LexiconResponse.DO_NOT_KNOW

    def register(self, words: List[str], response: LexiconResponse,
            to_skip: Optional[bool], date: Optional[datetime] = None,
            log_name: str = "log") -> None:
        """
        Register user's response.

        :param words: list of words that user was responded to.
        :param response: response type.
        :param to_skip: skip this word in the future.
        :param date: time of response.
        :param log_name: specifier of the log.
        """
        if not date:
            date = datetime.now()

        for word in words:
            self.words[word] = WordKnowledge(response, to_skip)

        if log_name not in self.logs:
            self.logs[log_name] = []
        self.logs[log_name].append(LogRecord(date, words, response))

        if response in [LexiconResponse.KNOW, LexiconResponse.DO_NOT_KNOW]:
            self.dates.append(date)
            self.responses.append(1 if response == LexiconResponse.KNOW else 0)

            if not self.start or date < self.start:
                self.start = date
            if not self.finish or date > self.finish:
                self.finish = date

    def get_statistics(self) -> float:
        count: List[int] = [0, 0]
        for record in self.logs["log"]:  # type: LogRecord
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

    def get_log_size(self) -> int:
        result: int = 0
        for record in self.logs["log"]:  # type: LogRecord
            if record.response in [
                    LexiconResponse.KNOW, LexiconResponse.DO_NOT_KNOW]:
                result += 1
        return result

    def count_unknowns(self) -> int:
        result: int = 0
        for record in self.logs["log"]:  # type: LogRecord
            if record.response in [LexiconResponse.DO_NOT_KNOW]:
                result += 1
        return result

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

    def get_average(self, index_1: Optional[int] = None,
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

    def construct(self, output_file_name: str, precision: int,
            first: Callable, next_: Callable) -> Dict:
        """
        Construct data file with statistics.

        ============= =======================
        point of time ratio multiplied by 100
        ============= =======================

        :param output_file_name: name of output data file in the format of
            space-separated values.
        :param precision: ratio precision.
        :param first: function that computes the point of time to start with.
        :param next_: function that computes the next point of time.
        """
        if not self.start:
            return {"current_percent": 0}

        output: TextIO = open(output_file_name, "w+")

        points = {}
        point: datetime = first(self.start)

        while point <= datetime.now():
            next_point: datetime = next_(point)
            length, data = self.get_data(point, next_point)
            points[point] = [length, data]
            point = next_point

        data = None
        preferred = None
        length = None
        percent = None

        for current_index in range(len(points)):
            m = sorted(points.keys())[current_index]
            sample_length, responses = points[m]

            if sample_length != 0 and precision != 0:
                percent = sample_length / precision * \
                    (1 - responses / sample_length) * 100
            else:
                percent = 0

            auxiliary_index = current_index
            length, data = 0, 0

            while auxiliary_index >= 0:
                sample_length, responses = \
                    points[sorted(points.keys())[auxiliary_index]]
                length += sample_length
                data += responses
                if length and 1 - data / length:
                    if self.language == "ru":
                        preferred = precision / (1 - data / length)
                    else:
                        preferred = precision / (1 - data / length)
                else:
                    preferred = 10000000

                if length >= preferred:
                    current_rate = rate(1 - data / length)
                    output.write(
                        f"    {m.strftime('%Y.%m.%d')} {current_rate:f}\n")
                    break

                auxiliary_index -= 1

        if preferred > length:
            print(f"Need {int(preferred - length)!s} more.")
            print(f"Need {100 - (length - data)!s} more wrong answers.")

        output.close()

        return {"current_percent": percent}

    def construct_precise(self, output_file_name: str) -> None:
        output = open(output_file_name, "w+")
        left = 0
        right = 0
        knowns = 0
        unknowns = 0
        while right < len(self.dates) - 1:
            date = self.dates[right]
            if knowns + unknowns:
                current_rate = unknowns / float(knowns + unknowns)
            else:
                current_rate = 0
            if unknowns >= 100:
                output.write(
                    f"    {date.strftime('%Y.%m.%d')} {rate(current_rate):f}\n")

                response = self.responses[left]
                if response == 1:
                    knowns -= 1
                if response == 0:
                    unknowns -= 1
                left += 1

            right += 1
            response = self.responses[right]
            if response == 1:
                knowns += 1
            if response == 0:
                unknowns += 1

        output.close()

    def get_rate(self, point_1: datetime, point_2: datetime) -> \
            (Optional[float], Optional[float]):
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
            return \
                rate(self.get_average(index_2 - preferred_interval, index_2)), \
                (index_2 - index_1) / preferred_interval
        elif index_2:
            return None, (index_2 - index_1) / preferred_interval

        return None, None

    def get_top_unknown(self, frequency_list: FrequencyList) -> List[str]:
        """
        Get all words user marked as unknown in order of frequency.

        :param frequency_list: sort words using this list.
        """
        result: List[str] = []

        for word in sorted(self.words.keys(),
                key=lambda x: -frequency_list.get_occurrences(x)):
            word_knowledge = self.words[word]
            if word_knowledge.knowing == LexiconResponse.DO_NOT_KNOW:
                result.append(word)

        return result

    def ask(self, word: str, wiktionary_word_list,
            dictionaries: List[Dictionary], skip_known: bool = False,
            skip_unknown: bool = False, log_name: str = "log") \
            -> (bool, LexiconResponse, Optional[Dictionary]):
        """
        Ask user if the word is known.
        """
        print("\n    " + word + "\n")

        if wiktionary_word_list:
            if word + "\n" in wiktionary_word_list:
                print("\033[32mIn Wiktionary.\033[0m")
            else:
                print("\033[31mNot in Wiktionary.\033[0m")
            if word[0].upper() + word[1:] + "\n" in wiktionary_word_list:
                print("\033[32mCapitalized in Wiktionary.\033[0m")
            else:
                print("\033[31mCapitalized not in Wiktionary.\033[0m")

        if self.has(word):
            print("Last response was: " + self.get(word).get_message() + ".")

        answer = None

        dictionary: Optional[Dictionary] = None
        for current_dictionary in dictionaries:
            print("Try " + current_dictionary.get_name() + "...")
            answer: Optional[str] = current_dictionary.get(word)
            if answer is not None:
                dictionary = current_dictionary
                break

        if answer is not None:
            one_button("Show answer")
            print(answer)

        print("Do you know at least one meaning of this word? [Y/n/b/s/q]> ")
        answer = get_char()
        while answer not in ["y", "Y", "Enter", "n", "N", "b", "B", "s", "S",
                "-", "q", "Q"]:
            answer = get_char()

        if answer in ["y", "Enter"]:
            print("Know.")
            answer = "y"
        elif answer in ["n", "N"]:
            print("Don't know.")
            answer = "n"
        elif answer in ["b", "B"]:
            print("Don't know, but it is a proper name too.")
            answer = "nb"
        elif answer in ["s", "S"]:
            print("Know and skip this word in the future.")
            answer = "ys"
        elif answer in ["q", "Q"]:
            print("Quit.")
            self.write()
            return False, None, None

        to_skip, response = process_response(skip_known, skip_unknown, answer)
        self.register([word], response, to_skip, log_name=log_name)

        return to_skip, response, dictionary

    def check(self, frequency_list: FrequencyList, stop_at: Optional[int],
            dictionaries: List[Dictionary], log_type: str,
            skip_known: bool, skip_unknown: bool,
            stop_at_wrong: Optional[int]) -> None:
        """
        Check current user vocabulary.

        :param frequency_list: list of the words with frequency to check.
        :param stop_at: stop after a number of actions.
        :param dictionaries: offer a translation from one of dictionaries.
        :param log_type: the method of picking words.
        :param skip_known: skip this word in the future if it is known.
        :param skip_unknown: skip this word in the future if it is unknown.
        :param stop_at_wrong: stop after a number of unknown words.
        """

        # Actions during current session:
        actions = 0
        wrong_answers = 0

        wiktionary_word_list = None

        if os.path.isdir("dictionary"):
            for dictionary_file_name in os.listdir("dictionary"):
                matcher = re.match(self.language +
                    r"wiktionary-\d*-all-titles-.*", dictionary_file_name)
                if matcher:
                    wiktionary_word_list = \
                        open(os.path.join(
                            "dictionary", dictionary_file_name)).readlines()
                    break

        if log_type == "frequency":
            log_name = "log"
        elif log_type == "random":
            log_name = "log_random"
        else:
            print("ERROR: unknown log type")
            return

        while True:
            picked_word = None
            if log_type == "frequency":
                picked_word, occurrences = \
                    frequency_list.get_random_word_by_frequency()
            elif log_type == "random":
                picked_word, occurrences = frequency_list.get_random_word()

            if self.do_skip(picked_word, skip_known, skip_unknown, log_name):
                continue

            to_skip, response, dictionary = self.ask(picked_word,
                wiktionary_word_list, dictionaries, skip_known, skip_unknown,
                log_name=log_name)
            actions += 1
            if response == LexiconResponse.DO_NOT_KNOW:
                wrong_answers += 1
            self.write()

            average = self.get_average()

            precision = self.count_unknowns() / 100
            rate_string = f"{rate(average):.2f}" if rate(average) else "unknown"
            if precision < 1:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Rate so far is: {rate_string}")
            else:
                print(f"Precision: {precision * 100:.2f}")
                print(f"Rate is: {rate_string}")
            print(f"Words: {len(self.words):d}")

            if not response:
                break

            if stop_at and actions >= stop_at:
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                break

    def do_skip(self, picked_word: str, skip_known: bool, skip_unknown: bool,
            log_name: str) -> bool:

        if self.has(picked_word) and \
            (self.words[picked_word].to_skip or
                self.get(picked_word) == LexiconResponse.NOT_A_WORD or
            (skip_known and
                self.get(picked_word) == LexiconResponse.KNOW) or
            (skip_unknown and
                self.get(picked_word) == LexiconResponse.DO_NOT_KNOW)):

            print("[skip] " + picked_word)
            response = self.get(picked_word)
            to_skip = self.words[picked_word].to_skip
            self.register([picked_word], response, to_skip, log_name=log_name)
            return True

        # Mark word as "not a word" if it contains symbols that do not appear
        # in language.

        foreign = False
        if self.language in symbols.keys():
            for symbol in picked_word:
                if symbol not in symbols[self.language]:
                    foreign = True
                    break

        if foreign:
            print("[forg] " + picked_word)
            self.register([picked_word], LexiconResponse.NOT_A_WORD, True,
                log_name=log_name)
            return True

        return False

    def print_statistics(self) -> None:
        count_ratio: float = self.get_statistics()

        print("Skipping:          %9.4f" %
              (len(self.logs["log"]) / len(self.words)))
        print("Count ratio:       %9.4f %%" % (count_ratio * 100))
        print("Words:             %4d" % len(self.words))
        # print("All words:         %4d" % len(frequency.words))
        print("Size:              %4d" % self.get_log_size())

    def __len__(self) -> int:
        return len(self.words)


class UserLexicon:
    def __init__(self, user_name: str, input_directory: str):
        self.user_name = user_name
        self.input_directory = input_directory

        self.lexicons = {}

        for file_name in os.listdir(input_directory):
            if not file_name.endswith(".json"):
                continue
            ln = 4
            current_user_name = file_name[:-4 - ln]
            if user_name == current_user_name:
                language = file_name[-3 - ln:-1 - ln]
                lexicon = \
                    Lexicon(language, os.path.join(input_directory, file_name))
                lexicon.read()
                self.lexicons[language] = lexicon


def process_response(skip_known: bool, skip_unknown: bool, answer: str) \
        -> (bool, LexiconResponse):
    """
    Process user response.

    :param skip_known: skip word in the future if user know it
    :param skip_unknown: skip word in the future if user don't know it
    :param answer: user response

    :return if word should be skipped in the future, word response
    """
    to_skip: bool = False
    if not answer or answer.lower() == "y":
        response = LexiconResponse.KNOW
        to_skip = skip_known
    elif answer.lower() == "ys":
        response = LexiconResponse.KNOW
        to_skip = True
    elif answer.lower() == "n":
        response = LexiconResponse.DO_NOT_KNOW
        to_skip = skip_unknown
    elif answer.lower() == "ns":
        response = LexiconResponse.DO_NOT_KNOW
        to_skip = True
    elif answer.lower() == "nb":
        response = LexiconResponse.DO_NOT_BUT_PROPER_NOUN_TOO
        to_skip = skip_unknown
    elif answer.lower() == "-":
        response = LexiconResponse.NOT_A_WORD
    else:
        response = LexiconResponse.DO_NOT_KNOW

    return to_skip, response
