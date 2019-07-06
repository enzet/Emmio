import math
import os
import re
import yaml

from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from engine.frequency_list import FrequencyList
from engine.language import symbols
from engine import ui


RESPONSE_KNOW = "know"
RESPONSE_DO_NOT_KNOW = "dont"
RESPONSE_KNOW_OR_NOT_A_WORD = "know_or_not_a_word"
RESPONSE_DO_NOT_BUT_PROPER_NOUN_TOO = "dont_but_proper_noun_too"
RESPONSE_NOT_A_WORD = "not_a_word"


class WordKnowledge:
    def __init__(self, knowing: str, to_skip: bool):
        self.knowing = knowing
        self.to_skip = to_skip

    def to_structure(self) -> Dict[str, Any]:
        structure = {"knowing": self.knowing}
        if self.to_skip:
            structure["to_skip"] = self.to_skip
        return structure


class LogRecord:
    def __init__(self, word, date, response):
        self.word = word
        self.date = date
        self.response = response


def first_day_of_month(point):
    return datetime(year=point.year, month=point.month, day=1)


def plus_month(point):
    new_year = point.year
    new_month = point.month + 1
    if new_month > 12:
        new_month = 1
        new_year = point.year + 1
    return datetime(year=new_year, month=new_month, day=1)


def first_day_of_week(point):
    day = point.date() - timedelta(days=point.weekday())
    return datetime.combine(day, datetime.min.time())


def rate(ratio: float) -> Optional[float]:
    if not ratio:
        return None
    return -math.log(ratio, 2)


class Lexicon:
    """
    Tracking of lexicon for one particular language through time.
    """
    def __init__(self, language: str, file_name: str) -> None:

        self.language = language
        self.file_name = file_name

        self.words = {}
        self.logs = {}

        self.dates = []
        self.responses = []
        self.start = None
        self.finish = None

    def read(self) -> None:
        ui.write("Reading lexicon from " + self.file_name + "...")

        data = yaml.load(open(self.file_name, "r"))

        for word in data["words"]:
            record = data["words"][word]
            if isinstance(record, list):
                self.words[word] = WordKnowledge(record[1], False)
            elif isinstance(record, dict):
                to_skip = False
                if "to_skip" in record:
                    to_skip = record["to_skip"]
                self.words[word] = WordKnowledge(record["knowing"], to_skip)

        for key in data:
            if key.startswith("log"):
                self.logs[key] = data[key]

        self.fill()

    def read_fast(self) -> None:
        ui.write("Reading lexicon...")

        mode = None
        log_name = None

        lines = open(self.file_name).readlines()
        lines_number = len(lines)

        for index, line in enumerate(lines):
            ui.progress_bar(index, lines_number)
            if line.startswith("log"):
                mode = "expect_log"
                log_name = line[:-2]
                self.logs[log_name] = []
                continue
            if line.startswith("words:"):
                mode = "expect_words"
                continue

            if mode in ["expect_log", "expect_log_ex"]:
                date_string = line[4:23]
                word = line[27:line.find("'", 28)]
                response = line[line.find("'", 28) + 3:-2]
                if mode == "expect_log":
                    self.logs[log_name].append([date_string, word, response])
            elif mode == "expect_words":
                k = line.find("knowing: ")
                t = line.find("to_skip: ")
                word = line[3:line.find("'", 3)]
                to_skip = False

                if t == -1:
                    knowing = line[k + 9:line.find("}", k)]
                else:
                    knowing = line[k + 9:line.find(",", k)]
                    to_skip = line[t + 9:line.find("}", t)] == "True"

                self.words[word] = WordKnowledge(knowing, to_skip)

        ui.progress_bar(-1, 0)

        self.fill()

    def fill(self):
        for date_string, word, response in self.logs["log"]:
            if response in [RESPONSE_KNOW, RESPONSE_DO_NOT_KNOW]:
                date = datetime.strptime(date_string, "%Y.%m.%d %H:%M:%S")
                self.dates.append(date)
                self.responses.append(1 if response == RESPONSE_KNOW else 0)

                if not self.start:
                    self.start = date
                self.finish = date

    def write(self) -> None:
        """
        Write lexicon to a file using YAML dumping. Should be slower than
        `write_fast` but more accurate.

        :param file_name: output YAML file name.
        """
        words_structure = {}
        for word in self.words:
            words_structure[word] = self.words[word].to_structure()

        data = {"words": words_structure}
        for key in sorted(self.logs):
            data[key] = self.logs[key]
        yaml.safe_dump(data, open(self.file_name, "w"), allow_unicode=True)

    def write_fast(self) -> None:
        """
        Write lexicon to a file using simple printing. Should be faster than
        `write` but less accurate.

        :param file_name: output YAML file name.
        """
        # ui.write("Writing lexicon to " + self.file_name + "...")

        with open(self.file_name, "w") as output:
            for key in sorted(self.logs):
                output.write(key + ":\n")
                for date, word, response in self.logs[key]:
                    output.write("- ['" + date + "', '" + word + "', " +
                        response + "]\n")
            output.write("words:\n")
            for word in sorted(self.words):
                element = self.words[word]
                output.write("  '" + word + "': {knowing: " +
                    element.knowing)
                if element.to_skip:
                    output.write(", to_skip: " + str(element.to_skip))
                output.write("}\n")

    def know(self, word: str) -> bool:
        """
        Check if user knows the word.
        """
        return self.words[word].knowing in \
               [RESPONSE_KNOW, RESPONSE_DO_NOT_BUT_PROPER_NOUN_TOO]

    def do_not_know(self, word: str) -> bool:
        """
        Check if user doesn't know the word.
        """
        return self.words[word].knowing == RESPONSE_DO_NOT_KNOW

    def register(self, word: str, response: str,
            to_skip: bool, date: datetime=None, log_name="log") -> None:
        """
        Register user's response.

        :param word: word that user was responded to.
        :param response: response type.
        :param to_skip: skip this word in the future.
        :param date: time of response
        :param log_name: specifier of the log
        """
        if not date:
            date = datetime.now()

        if response == RESPONSE_KNOW_OR_NOT_A_WORD and word in self.words:
            return

        self.words[word] = WordKnowledge(response, to_skip)

        if log_name not in self.logs:
            self.logs[log_name] = []
        self.logs[log_name].append(
            [date.strftime("%Y.%m.%d %H:%M:%S"), word, response])

        if response in [RESPONSE_KNOW, RESPONSE_DO_NOT_KNOW]:
            self.dates.append(date)
            self.responses.append(1 if response == RESPONSE_KNOW else 0)

            if not self.start or date < self.start:
                self.start = date
            if not self.finish or date > self.finish:
                self.finish = date

    def get_statistics(self) -> (float, float):
        count = [0, 0]
        for date, word, response in self.logs["log"]:
            if response == RESPONSE_KNOW:
                count[0] += 1
            elif response == RESPONSE_DO_NOT_KNOW:
                count[1] += 1

        count_ratio = 0
        if count[0] + count[1]:
            count_ratio = count[0] / (count[0] + count[1])

        return count_ratio

    def has(self, word: str) -> bool:
        return word in self.words

    def get(self, word: str) -> str:
        return self.words[word].knowing

    def get_log_size(self) -> int:
        result = 0
        for date, word, response in self.logs["log"]:
            if response in [RESPONSE_KNOW, RESPONSE_DO_NOT_KNOW]:
                result += 1
        return result

    def count_unknowns(self) -> int:
        result = 0
        for date, word, response in self.logs["log"]:
            if response in [RESPONSE_DO_NOT_KNOW]:
                result += 1
        return result

    def get_bounds(self, point_1, point_2):

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

    def get_average(self, index_1: int=None, index_2: int=None) -> \
            Optional[float]:
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

    def get_data(self, start, finish):
        length = 0
        data = 0
        for i in range(len(self.dates)):
            if start <= self.dates[i] < finish:
                length += 1
                data += self.responses[i]
        return length, data

    def get_preferred_interval(self):
        return int(100 / self.get_average())

    def construct(self, output_file_name: str, precision: int, first, next_) -> \
            None:
        """
        Construct data file with month-by-month statistics.

        ==== =======================
        date ratio multiplied by 100
        ==== =======================

        :param output_file_name: name of output data file in the format of
            space-separated values.
        """
        output = open(output_file_name, "w+")

        average = self.get_average()
        preferred_interval = self.get_preferred_interval()

        print(self.language + ":")
        # print("Average:", average)
        # print("Preferred interval:", preferred_interval)

        points = {}
        point = first(self.start)
        while point <= datetime.now():  # self.finish:
            next_point = next_(point)
            length, data = self.get_data(point, next_point)
            points[point] = [length, data]
            point = next_point

        last = 0

        for current_index in range(len(points)):
            m = sorted(points.keys())[current_index]
            sample_length, responses = points[m]

            try:
                percent = sample_length / \
                    (100 / (1 - responses / sample_length)) * 100
            except Exception:
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
                    color = "0m  " if (last == current_rate) else \
                        ("32m ▲" if (last < current_rate) else "31m ▼")
                    last = current_rate
                    print("%s  %3d %%  \033[%s %7.4f\033[0m" %
                        (m.strftime("%Y.%m.%d"), percent,
                            color, current_rate))
                    output.write("    %s %f\n" %
                        (m.strftime("%Y.%m.%d"), current_rate))
                    break
                elif auxiliary_index == 0:
                    print("%s  %3d %%" %
                          (m.strftime("%Y.%m.%d"), percent))
                auxiliary_index -= 1

        if preferred > length:
            print("Need " + str(int(preferred - length)) + " more.")

        output.close()

    def get_last_rate(self) -> (float, float):
        """
        Get rate for the last month.
        """
        now = datetime.now()
        point = datetime(year=now.year, month=now.month, day=1)
        next_point = plus_month(point)
        return self.get_rate(point, next_point)

    def get_rate(self, point_1: datetime, point_2: datetime) -> \
            (Optional[float], float):
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

    def get_top_unknown(self):

        result = []

        for word in sorted(self.words.keys(),
                key=lambda x: -self.words[x].occurrences):
            word_knowledge = self.words[word]
            if word_knowledge.knowing == RESPONSE_DO_NOT_KNOW:
                result.append([word, word_knowledge])

        return result

    def ask(self, word: str, wiktionary_word_list, dictionary,
            skip_known: bool, skip_unknown: bool, log_name: str):

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
            print("WAS " + self.get(word))

        if dictionary:
            if dictionary.has(word):
                input("Try to remember. ")
                print(dictionary.get(word))

        print("Do you know at least one meaning of this word?")
        answer = ui.get_char()
        while answer not in ["y", "Enter", "n", "q"]:
            answer = ui.get_char()

        if answer == "q":
            self.write_fast()
            return False

        to_skip, response = process_response(skip_known, skip_unknown, answer)
        self.register(word, response, to_skip, log_name=log_name)

        return response

    def check(self, frequency_list: FrequencyList, stop_at,
            dictionary, log_type, skip_known, skip_unknown):

        actions = 0

        wiktionary_word_list = None

        if os.path.isfile("dictionary"):
            for dictionary_file_name in os.listdir("dictionary"):
                matcher = re.match(self.language +
                    "wiktionary-\d*-all-titles-.*", dictionary_file_name)
                if matcher:
                    wiktionary_word_list = \
                        open(os.path.join("dictionary", dictionary_file_name)) \
                            .readlines()
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

            response = self.ask(picked_word, wiktionary_word_list,
                dictionary, skip_known, skip_unknown,
                log_name=log_name)
            actions += 1
            self.write_fast()

            average = self.get_average()

            precision = self.count_unknowns() / 100
            rate_string = "%.2f" % rate(average) if rate(average) else "unknown"
            if precision < 1:
                print("Precision: %.0f %%" % (precision * 100))
                print("Rate so far is: %s" % rate_string)
            else:
                print("Precision: %.0f %%" % (precision * 100))
                print("Rate is: %s" % rate_string)

            if not response:
                break

            if stop_at and actions >= stop_at:
                break

    def do_skip(self, picked_word, skip_known, skip_unknown, log_name):
        if self.has(picked_word) and \
                (self.words[picked_word].to_skip or
                 self.get(picked_word) == RESPONSE_NOT_A_WORD or
                 (skip_known and
                  self.get(picked_word) == RESPONSE_KNOW) or
                 (skip_unknown and
                  self.get(picked_word) == RESPONSE_DO_NOT_KNOW)):

            print("[skip] " + picked_word)
            response = self.get(picked_word)
            to_skip = self.words[picked_word].to_skip
            self.register(picked_word, response, to_skip,
                log_name=log_name)
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
            self.register(picked_word, RESPONSE_NOT_A_WORD, True,
                log_name=log_name)
            return True

        return False

    def print_statistics(self):
        count_ratio = self.get_statistics()

        print("Skipping:          %9.4f" %
              (len(self.logs["log"]) / len(self.words)))
        print("Count ratio:       %9.4f %%" % (count_ratio * 100))
        print("Words:             %4d" % len(self.words))
        # print("All words:         %4d" % len(frequency.words))
        print("Size:              %4d" % self.get_log_size())
        rate, percent = self.get_last_rate()
        if rate is not None:
            print("Rate:              %9.4f" % rate)
        if percent is not None:
            print("Last month:        %9.4f %%" % (percent * 100))

    def __len__(self):
        return len(self.words)


def process_response(skip_known: bool, skip_unknown: bool, answer: str) \
        -> (bool, str):
    """
    Process user response.

    :param skip_known: skip word in the future if user know it
    :param skip_unknown: skip word in the future if user don't know it
    :param answer: user response

    :return if word should be skipped in the future, word response
    """
    to_skip = False
    if not answer or answer.lower() == "y":
        response = RESPONSE_KNOW
        to_skip = skip_known
    elif answer.lower() == "ys":
        response = RESPONSE_KNOW
        to_skip = True
    elif answer.lower() == "n":
        response = RESPONSE_DO_NOT_KNOW
        to_skip = skip_unknown
    elif answer.lower() == "ns":
        response = RESPONSE_DO_NOT_KNOW
        to_skip = True
    elif answer.lower() == "nb":
        response = RESPONSE_DO_NOT_BUT_PROPER_NOUN_TOO
        to_skip = skip_unknown
    elif answer.lower() == "-":
        response = RESPONSE_NOT_A_WORD
    else:
        response = RESPONSE_DO_NOT_KNOW

    return to_skip, response



