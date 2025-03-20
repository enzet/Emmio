"""Core functionality for lexicon."""

import json
import math
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Self, override

from pydantic import BaseModel

from emmio.core import Record, Session
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    DictionaryItem,
)
from emmio.language import ENGLISH, RUSSIAN, Language
from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.core import SentencesCollection
from emmio.ui import Block, Element, Interface, Text
from emmio.user.core import UserArtifact

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DATE_FORMAT: str = "%Y.%m.%d %H:%M:%S"


class LexiconResponse(Enum):
    """User response or propagation of user response."""

    UNKNOWN = "unknown"

    KNOW = "know"
    """User knows at least one meaning of the word."""

    DONT = "dont"
    """User doesn't know any meaning of the word."""

    KNOW_OR_NOT_A_WORD = "know_or_not_a_word"
    """
    User knows at least one meaning of the word or the string is not a word.
    """

    DONT_BUT_PROPER_NOUN_TOO = "dont_but_proper_noun_too"
    """User doesn't know the word, but it is often used as a proper noun."""

    NOT_A_WORD = "not_a_word"
    """The string is not a dictionary word.

    This may be misspelling, non-dictionary onomatopoeic word, foreign word,
    etc. A frequency list may contain such words if it was not filtered using
    the dictionary.
    """

    def to_string(self) -> str:
        """Get string identifier of the response."""
        return self.name.lower()

    @classmethod
    def from_string(cls, string: str) -> Self:
        """Get response from string identifier."""
        return cls[string.upper()]

    def get_symbol(self) -> str:
        """Get short symbol for the response."""
        match self:
            case self.KNOW:
                return "K"
            case self.DONT:
                return "D"
            case self.KNOW_OR_NOT_A_WORD:
                return "?"
            case self.DONT_BUT_PROPER_NOUN_TOO:
                return "B"
            case self.NOT_A_WORD:
                return "N"

        raise ValueError("Unknown response type")

    def get_message(self) -> str:
        """Get human-readable message for the response."""
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

        raise ValueError("Unknown response type")


class AnswerType(Enum):
    """Type of the answer: how it was obtained."""

    UNKNOWN = "unknown"
    """Answer type is unknown."""

    USER_ANSWER = "user_answer"
    """User answer."""

    ASSUME__NOT_A_WORD__ALPHABET = "assume_not_a_word"
    """It was automatically assumed that the word contain non-language symbols.

    We have a list of all possible symbols in the language, and the word
    contains at least one symbol that is not in the list, meaning that the word
    is probably a foreign or some special word.
    """

    ASSUME__NOT_A_WORD__DICTIONARY = "assume_not_a_word_dict"
    """It was automatically assumed that the word is not a dictionary word.

    We have one or several dictionaries, that we suppose contain all possible
    words in the language, but the word is not in any of them.
    """

    PROPAGATE__SKIP = "propagate_skip"
    """Previous answer was propagated because of a special flag set by the user.

    The user has set a flag that the word should be skipped, and the word should
    not be checked again.
    """

    PROPAGATE__NOT_A_WORD = "propagate_not_a_word"
    """Word is not a dictionary word, and this answer was propagated."""

    PROPAGATE__TIME = "propagate_time"
    """Not enough time passed since last answer, therefore it was propagated.

    Time for different answer types are user-defined.
    """

    def __str__(self) -> str:
        """Get string identifier of the answer type."""
        return self.value

    def __repr__(self) -> str:
        """Get string identifier of the answer type."""
        return self.value


def compute_lexicon_rate(
    data: list[tuple[datetime, int]],
    precision: int = 100,
) -> tuple[list[tuple[datetime, datetime]], list[float]]:
    """Given lexicon records, compute rate values with given precision.

    :param data: list of (response time, lexicon response), is assumed to be
        sorted by date
    :param precision: desired number of "don't know" answers
    :return: list of ((start date, end date), rate value)
    """

    # Indices of "don't know" answers.
    unknown_indices: list[int] = [
        index for index, (_, response) in enumerate(data) if response == 0
    ]

    # If we don't have enough "don't know" answers, return empty lists.
    if len(unknown_indices) < precision:
        return [], []

    date_ranges: list[tuple[datetime, datetime]] = []
    rate_values: list[float] = []

    index: int = 0
    while index <= len(unknown_indices) - precision:
        data_index_1: int = unknown_indices[index - 1] + 1 if index > 0 else 0
        data_index_2: int = unknown_indices[index + precision - 1]
        length: int = data_index_2 - data_index_1 + 1
        number_of_knows: int = sum(
            x[1] for x in data[data_index_1 : data_index_2 + 1]
        )
        current_rate: float | None = rate((length - number_of_knows) / length)
        if current_rate is not None:
            rate_values.append(current_rate)
            date_ranges.append((data[data_index_1][0], data[data_index_2][0]))
            index += 1

    return date_ranges, rate_values


@dataclass
class WordKnowledge:
    """User's knowledge of a word."""

    knowing: LexiconResponse
    """Last user's response to the word."""

    to_skip: bool | None
    """Whether to skip this word in the future."""

    def to_structure(self) -> dict[str, Any]:
        """Serialize to structure."""
        structure: dict[str, Any] = {"knowing": str(self.knowing)}
        if self.to_skip is not None:
            structure["to_skip"] = self.to_skip
        return structure

    def to_json_str(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_structure(), ensure_ascii=False)


class LexiconLogSession(Session):
    """User session of checking lexicon."""

    def end_session(self, time: datetime) -> None:
        """Mark session as finished at the specified time.

        :param time: time when session was finished
        :param actions: number of actions performed during the session
        """
        self.end = time


class LexiconLogRecord(Record):
    """Record of user's answer."""

    word: str
    """Word that was checked."""

    response: LexiconResponse
    """User's response."""

    answer_type: AnswerType | None = None
    """Type of the answer."""

    to_skip: bool | None = None
    """Skip this word in the future."""

    @override
    def get_symbol(self) -> str:
        """Get short symbol for the lexicon record."""
        return self.response.get_symbol()


def rate(ratio: float) -> float | None:
    """Compute Emmio lexicon rating.

    Rate is just a more readable representation of the ratio of unknown words.

    :param ratio: the ratio of unknown words to all words in some text, corpus
        of texts or some random sample of text or corpus of texts
    :return rating or None if ratio is 0
    """
    if not ratio:
        return None
    return -math.log(ratio, 2)


class WordSelection(Enum):
    """How to select words for checking."""

    ARBITRARY = "arbitrary"
    """Select words arbitrarily."""

    RANDOM_WORD_FROM_LIST = "random"
    """Select a word randomly from a list of all unique words.

    Note, that is not the same as selecting a random word from the whole
    corpus of texts.
    """

    FREQUENCY = "frequency"
    """Select word randomly from the corpus of texts.

    This is the same as selecting words from frequency list, taking into account
    the frequency of the words.
    """

    UNKNOWN = "unknown"
    """Select unknown words."""

    TOP = "top"
    """Select most frequent words first."""


class LexiconLog(BaseModel):
    """Registered answers to words from lexicon."""

    records: list[LexiconLogRecord] = []
    """Answers to words from lexicon."""

    sessions: list[LexiconLogSession] = []
    """Sessions in which lexicon was checked."""

    def model_dump_json(self, *args, **kwargs) -> str:
        """Serialize to JSON string.

        This field order is such for historical reasons. We should change it in
        the future.
        """
        order: list[str] = [
            "word",
            "response",
            "answer_type",
            "to_skip",
            "time",
        ]
        data: dict = super().model_dump(mode="json", exclude_none=True)
        records: list[dict[str, Any]] = [
            OrderedDict((key, record[key]) for key in order if key in record)
            for record in data["records"]
        ]
        return json.dumps(
            {"records": records, "sessions": data["sessions"]},
            ensure_ascii=False,
            *args,
            **kwargs,
        )


@dataclass
class Lexicon(UserArtifact):
    """Tracking of lexicon for one particular language through time."""

    log: LexiconLog
    """Log of lexicon."""

    language: Language
    """Language of the lexicon."""

    config: LexiconConfig
    """Configuration of the lexicon."""

    words: dict[str, WordKnowledge]
    """Words in the lexicon."""

    dates: list[datetime]
    """Dates of the answers."""

    responses: list[int]
    """Responses of the answers."""

    start: datetime | None
    """Start date of the lexicon."""

    finish: datetime | None
    """Finish date of the lexicon."""

    @classmethod
    def from_config(cls, path: Path, id_: str, config: LexiconConfig) -> Self:
        """Initialize lexicon.

        :param path: path to the directory with lexicon files
        :param config: lexicon configuration
        """
        language: Language = Language.from_code(config.language)

        file_path: Path = path / config.file_name

        words: dict[str, WordKnowledge] = {}
        dates: list[datetime] = []
        responses: list[int] = []
        start: datetime | None = None
        finish: datetime | None = None

        # Read data from file.

        if not file_path.exists():
            with file_path.open("w+", encoding="utf-8") as output:
                output.write("{}")

        with file_path.open(encoding="utf-8") as input_file:
            data = json.load(input_file)

        log: LexiconLog = LexiconLog(**data)

        for record in log.records:
            words[record.word] = WordKnowledge(record.response, record.to_skip)

        # Fill data.

        for record in log.records:
            if record.response in [
                LexiconResponse.KNOW,
                LexiconResponse.DONT,
            ]:
                dates.append(record.time)
                responses.append(
                    1 if record.response == LexiconResponse.KNOW else 0
                )

                if start is None:
                    start = record.time
                finish = record.time

        return cls(
            id_,
            file_path,
            log,
            language,
            config,
            words,
            dates,
            responses,
            start,
            finish,
        )

    def dump_json(self) -> str:
        """Serialize lexicon to a JSON string."""
        return self.log.model_dump_json(indent=4)

    def know(self, word: str) -> bool:
        """Check if user knows the word."""
        if word not in self.words:
            return False
        return self.words[word].knowing in [
            LexiconResponse.KNOW,
            LexiconResponse.DONT_BUT_PROPER_NOUN_TOO,
        ]

    def do_not_know(self, word: str) -> bool:
        """Check if user doesn't know the word."""
        return self.words[word].knowing == LexiconResponse.DONT

    def get_last_answer(self, word: str) -> LexiconLogRecord | None:
        """Get last answer for the word."""

        for record in reversed(self.log.records):
            if word == record.word:
                return record

        return None

    def register(
        self,
        word: str,
        response: LexiconResponse,
        to_skip: bool | None,
        request_time: datetime | None,
        time: datetime | None = None,
        answer_type: AnswerType = AnswerType.UNKNOWN,
    ) -> None:
        """Register user's response.

        :param word: the question id that user was responded to.
        :param response: response type.
        :param to_skip: skip this word in the future.
        :param request_time: time of the question.
        :param time: time of the response.
        :param answer_type: is it was a user answer or the previous answer was
            used.
        """
        if not time:
            time = datetime.now()

        self.words[word] = WordKnowledge(response, to_skip)

        self.log.records.append(
            LexiconLogRecord(
                time=time,
                word=word,
                response=response,
                answer_type=answer_type,
                to_skip=to_skip,
                request_time=request_time,
            )
        )
        if response in [LexiconResponse.KNOW, LexiconResponse.DONT]:
            self.dates.append(time)
            self.responses.append(1 if response == LexiconResponse.KNOW else 0)

            if not self.start or time < self.start:
                self.start = time
            if not self.finish or time > self.finish:
                self.finish = time

    def has(self, word: str) -> bool:
        """Check whether there is a response in at least one log."""
        return word in self.words

    def get(self, word: str) -> LexiconResponse:
        """Get the most recent response from all logs."""
        return self.words[word].knowing

    def count_unknowns(
        self, after: datetime | None = None, before: datetime | None = None
    ) -> int:
        """Return the number of "Don't know" answers."""
        return [
            x.response
            for x in self.log.records
            if not after or not before or after <= x.time <= before
        ].count(LexiconResponse.DONT)

    def get_average(
        self, index_1: int | None = None, index_2: int | None = None
    ) -> float | None:
        """Get average ratio.

        :param index_1: start index
        :param index_2: finish index
        :return: average ratio or None if ratio is infinite
        """
        if not index_1 and not index_2:
            if len(self.responses) == 0:
                return None
            return 1 - (sum(self.responses) / len(self.responses))

        return 1 - (
            sum(self.responses[index_1:index_2])
            / len(self.responses[index_1:index_2])
        )

    def construct_precise(
        self, precision: int = 100, before: datetime | None = None
    ) -> tuple[list[tuple[datetime, datetime]], list[float]]:
        """Construct precise rate values for the lexicon.

        For all possible time intervals, just big enough to have a requested
        precision, compute the rate for this interval.

        :param precision: precision of the rate
        :param before: before this date
        :return: tuple of (date ranges, rate values for each date range)
        """
        # TODO: rename.

        dates_and_responses: list[tuple[datetime, int]] = list(
            zip(self.dates, self.responses)
        )
        if before:
            dates_and_responses = [
                (date, response)
                for date, response in dates_and_responses
                if date <= before
            ]
        return compute_lexicon_rate(dates_and_responses, precision)

    def get_last_rate(
        self, precision: int = 100, before: datetime | None = None
    ) -> float | None:
        """Get last rate value.

        Get the rate of the last interval that gives the requested precision.

        :param precision: precision of the rate
        :param before: before this date
        :return: last rate value or None if there is no rate values
        """
        # TODO: rewrite, the implementation is too resource-consuming.

        _, rates = self.construct_precise(precision, before)
        if rates:
            return rates[-1]
        return None

    def get_precision_per_week(self) -> int:
        """Get precision value suggested to get every week."""
        return self.config.precision_per_week

    def get_last_rate_number(self, precision: int = 100) -> float:
        """Get last rate value.

        :param precision: precision of the rate
        :return: last rate value or 0.0 if there is no rate values
        """
        value: float | None = self.get_last_rate(precision)
        if value is None:
            return 0.0
        return value

    def get_top_unknown(self, frequency_list: FrequencyList) -> list[str]:
        """Get all words user marked as unknown in order of frequency.

        :param frequency_list: sort words using this list.
        """
        result: list[str] = []

        for word in sorted(
            self.words.keys(), key=lambda x: -frequency_list.get_occurrences(x)
        ):
            word_knowledge: WordKnowledge = self.words[word]
            if word_knowledge.knowing == LexiconResponse.DONT:
                result.append(word)

        return result

    def get_question(
        self,
        word: str,
        sentences: SentencesCollection | None,
    ) -> list[Element]:
        """Get question text for picked word to ask user."""

        result: list[Element] = []
        result.append(Block(word, (0, 0, 0, 4)))

        if self.has(word):
            result.append(
                Text(f"Last response was: {self.get(word).get_message()}.")
            )

        if sentences is not None:
            if sentence_translations := sentences.filter_by_word(
                word, set(), 120
            ):
                example: Text = Text(
                    f"Usage example: {sentence_translations[0].sentence.text}"
                )
                result.append(example)
        return result

    async def ask(
        self,
        interface: Interface,
        word: str,
        dictionaries: DictionaryCollection,
        sentences: SentencesCollection | None,
        skip_known: bool = False,
        skip_unknown: bool = False,
    ) -> tuple[bool | None, LexiconResponse | None, Dictionary | None]:
        """Ask user if the word is known.

        :return: tuple of (skip in future, response, dictionary)
        """

        # FIXME: get definitions languages from user settings.
        definitions_languages: list[Language] = [ENGLISH, RUSSIAN]

        for element in self.get_question(word, sentences):
            interface.print(element)

        start_time: datetime = datetime.now()

        translation: list[Element] | None = await dictionaries.to_text(
            word, self.language, definitions_languages
        )
        if translation is not None and translation:
            interface.button("Show translation")
            for element in translation:
                interface.print(element)

        answer: str = interface.choice(
            [
                ("Yes", "y"),
                ("No", "n"),
                ("Proper", "b"),
                ("Yes, skip", "s"),
                ("Not a word", "-"),
                ("Quit", "q"),
            ],
            "Do you know at least one meaning of this word?",
        )
        response: LexiconResponse
        skip_in_future: bool | None = None

        match answer:
            case "Yes":
                response = LexiconResponse.KNOW
            case "No":
                response = LexiconResponse.DONT
            case "Proper":
                response = LexiconResponse.DONT_BUT_PROPER_NOUN_TOO
            case "Yes, skip":
                response = LexiconResponse.KNOW
            case "Not a word":
                response = LexiconResponse.NOT_A_WORD
            case "Quit":
                self.write()
                return False, None, None
            case _:
                response = LexiconResponse.DONT

        interface.print(response.get_message())

        if skip_in_future is None:
            if response == LexiconResponse.KNOW:
                skip_in_future = skip_known
            elif response == LexiconResponse.DONT:
                skip_in_future = skip_unknown

        self.register(
            word,
            response,
            skip_in_future,
            start_time,
            answer_type=AnswerType.USER_ANSWER,
        )
        return skip_in_future, response, None

    async def binary_search(
        self,
        interface: Interface,
        frequency_list: FrequencyList,
        dictionaries: DictionaryCollection,
    ) -> None:
        """Try to find position of the balanced word.

        This is an experimental function. It's result has meaning only if it is
        repeated many times and the average is computed.

        Firstly, we try the random word of the frequency list. If it is known,
        we try the word in the middle of the right half, else we try the word
        in the middle of the left half.
        """
        left_border, right_border = 0, int((len(frequency_list) - 1) / 2)
        while True:
            print(left_border, right_border)
            index: int = int((left_border + right_border) / 2)
            picked_word, occurrences = frequency_list.get_word_by_index(index)
            print(occurrences)
            _, response, _ = await self.ask(
                interface,
                picked_word,
                dictionaries=dictionaries,
                sentences=None,
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

    def get_statistics(self) -> list[Element]:
        """Get current statistics of the lexicon."""

        precision: int = self.count_unknowns()
        average: float | None = self.get_average()
        rate_string: str = (
            f"{rate(average):.2f}"
            if average is not None and rate(average)
            else "unknown"
        )

        result: list[Element] = []
        if precision < 100:
            result.append(Text(f"Precision: {precision:.2f}"))
            result.append(Text(f"Rate so far is: {rate_string}"))
        else:
            result.append(Text(f"Precision: {precision:.2f}"))
            result.append(
                Text(f"Current rate is: {self.get_last_rate_number():.2f}")
            )
        result.append(Text(f"Words: {len(self.words):d}"))
        return result

    async def check(
        self,
        interface: Interface,
        user_data,
        frequency_list: FrequencyList,
        stop_at: int | None,
        dictionaries: DictionaryCollection,
        sentences: SentencesCollection | None,
        log_type: str,
        skip_known: bool,
        skip_unknown: bool,
        stop_at_wrong: int | None,
    ) -> str:
        """
        Check current user vocabulary.

        :param interface: interface for communicating with the user.
        :param frequency_list: list of the words with frequency to check.
        :param stop_at: stop after a number of actions.
        :param dictionaries: offer a translation from one of dictionaries.
        :param sentences: offer a sentence from one of sentence collections.
        :param log_type: the method of picking words.
        :param skip_known: skip this word in the future if it is known.
        :param skip_unknown: skip this word in the future if it is unknown.
        :param stop_at_wrong: stop after a number of unknown words.

        :return: exit code.
        """

        session: LexiconLogSession = LexiconLogSession(start=datetime.now())

        # Actions during current session:
        actions: int = 0
        wrong_answers: int = 0

        checked_in_session: set[str] = set()

        exit_code: str = "quit"

        mf_index: int = 0

        while True:

            # If all words are checked, exit. This case may happen only if the
            # frequency list is too small.
            if len(checked_in_session) >= len(frequency_list):
                break

            picked_word: str

            if log_type == "frequency":
                picked_word, _ = frequency_list.get_random_word_by_frequency()
            elif log_type == "random":
                picked_word, _ = frequency_list.get_random_word()
            elif log_type == "most frequent":
                picked_word, _ = frequency_list.get_word_by_index(mf_index)
                mf_index += 1
                if self.has(picked_word):
                    continue
                items: list[DictionaryItem] = await dictionaries.get_items(
                    picked_word, self.language
                )
                if not items or items[0].is_not_common(self.language):
                    continue
                print(f"[{mf_index}]")

            if picked_word:
                checked_in_session.add(picked_word)

            if self.do_skip(picked_word, user_data, skip_known, skip_unknown):
                continue

            _, response, _ = await self.ask(
                interface,
                picked_word,
                dictionaries,
                sentences,
                skip_known,
                skip_unknown,
            )
            actions += 1
            if response == LexiconResponse.DONT:
                wrong_answers += 1

            for element in self.get_statistics():
                interface.print(element)

            if not response:
                exit_code = "quit"
                break

            if stop_at and actions >= stop_at:
                exit_code = "limit"
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                exit_code = "limit"
                break

        session.end_session(datetime.now())
        self.log.sessions.append(session)
        self.write()

        return exit_code

    def do_skip(
        self,
        picked_word: str,
        user_data,
        skip_known: bool,
        skip_unknown: bool,
    ) -> bool:
        """Check whether the word should be skipped.

        :param picked_word: word to check
        :param user_data: user-specific data
        :param skip_known: if the known words should be skipped
        :param skip_unknown: if the unknown words should be skipped
        """
        lexicon_records: list[LexiconLogRecord] = []
        lexicon: Lexicon
        for lexicon in user_data.get_lexicons_by_language(self.language):
            if lexicon.has(picked_word):
                lexicon_records += lexicon.get_records(picked_word)

        lexicon_records = sorted(lexicon_records, key=lambda x: x.time)

        skip_markers: list[bool] = [
            x.to_skip for x in lexicon_records if x.to_skip is not None
        ]
        skip_marker: bool | None = None
        if skip_markers:
            skip_marker = skip_markers[-1]

        last_record: LexiconLogRecord | None = None
        if lexicon_records:
            last_record = lexicon_records[-1]

        if last_record is not None:
            if (
                skip_marker
                or skip_known
                and last_record.response == LexiconResponse.KNOW
                or skip_unknown
                and last_record.response == LexiconResponse.DONT
            ):
                self.register(
                    picked_word,
                    last_record.response,
                    skip_marker,
                    None,
                    answer_type=AnswerType.PROPAGATE__SKIP,
                )
                return True

            if last_record.response == LexiconResponse.NOT_A_WORD:
                self.register(
                    picked_word,
                    LexiconResponse.NOT_A_WORD,
                    None,
                    None,
                    answer_type=AnswerType.PROPAGATE__NOT_A_WORD,
                )
                return True

            was_answered_recently: bool = False

            for record in reversed(self.log.records):
                delta = datetime.now() - record.time
                if delta.days > 30:
                    break
                if (
                    picked_word == record.word
                    and record.answer_type == AnswerType.USER_ANSWER
                ):
                    was_answered_recently = True
                    break

            if was_answered_recently:
                self.register(
                    picked_word,
                    last_record.response,
                    None,
                    None,
                    answer_type=AnswerType.PROPAGATE__TIME,
                )
                return True

        # Mark word as "not a word" if it contains symbols that do not appear
        # in language.

        is_foreign: bool = False
        if (symbols := self.language.get_symbols()) and symbols:
            for symbol in picked_word:
                if symbol not in symbols:
                    is_foreign = True
                    break

        if is_foreign:
            print("[assume.not_a_word] " + picked_word)
            self.register(
                picked_word,
                LexiconResponse.NOT_A_WORD,
                None,
                None,
                answer_type=AnswerType.ASSUME__NOT_A_WORD__ALPHABET,
            )
            return True

        return False

    def __len__(self) -> int:
        return len(self.words)

    def __repr__(self) -> str:
        return f"<User lexicon {self.language.get_name()}>"

    def get_user_records(self, word: str) -> list[LexiconLogRecord]:
        """Get all records for a specific word."""

        records: list[LexiconLogRecord] = []
        for record in self.log.records:
            if (
                record.word == word
                and record.answer_type == AnswerType.USER_ANSWER
            ):
                records.append(record)
        return records

    def get_records(self, word: str | None = None) -> list[LexiconLogRecord]:
        """Get all records or records for a specific word."""
        if not word:
            return self.log.records
        return [x for x in self.log.records if x.word == word]

    def get_sessions(self) -> list[LexiconLogSession]:
        """Get all sessions."""
        return self.log.sessions

    def is_frequency(self) -> bool:
        """Check whether the lexicon selection is frequency.

        It allows to compute knowledge rate based on the frequency list.
        """
        return self.config.selection == LexiconSelection.FREQUENCY
