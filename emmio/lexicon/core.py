"""Core functionality for lexicon."""

import json
import logging
import math
import random
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Self, cast, override

import numpy as np
from pydantic import BaseModel
from scipy.optimize import minimize
from scipy.special import expit  # pylint: disable=no-name-in-module

from emmio import postgres
from emmio.core import Record, Session
from emmio.dictionary.core import (
    Dictionary,
    DictionaryCollection,
    DictionaryItem,
)
from emmio.language import KnownLanguages, Language
from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.config import SentencesUsageConfig
from emmio.sentence.core import Sentence, SentenceElement
from emmio.sentence.data import SentencesData
from emmio.ui import Block, Colorized, Element, Formatted, Interface, Text
from emmio.user.core import UserArtifact

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

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

    def to_code(self) -> str:
        """Get single-character code used to store the response in database.

        This code is persisted, so it must stay stable even if display symbols
        change. See `get_symbol` for the (currently identical) display symbol.
        """
        match self:
            case self.KNOW:
                return "K"
            case self.DONT:
                return "D"
            case self.NOT_A_WORD:
                return "N"
            case self.DONT_BUT_PROPER_NOUN_TOO:
                return "B"
            case self.KNOW_OR_NOT_A_WORD:
                return "?"
            case self.UNKNOWN:
                return "U"
            case _:
                message = f"No database code for response `{self}`."
                raise ValueError(message)

    @classmethod
    def from_code(cls, code: str) -> Self:
        """Get response from its database code."""
        for response in cls:
            if response.to_code() == code:
                return response

        message = f"Unknown response code `{code}`."
        raise ValueError(message)

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

        message = "Unknown response type"
        raise ValueError(message)

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

        message = "Unknown response type"
        raise ValueError(message)


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

    def is_user_answer(self) -> bool:
        """Check if the answer is a user answer."""
        return self == self.USER_ANSWER

    def to_code(self) -> str | None:
        """Get database code for the answer type.

        Returns `None` for answer types that are not stored explicitly: a user
        answer is the default and leaves the code absent in the database.
        """
        match self:
            case self.ASSUME__NOT_A_WORD__ALPHABET:
                return "aa"
            case self.ASSUME__NOT_A_WORD__DICTIONARY:
                return "ad"
            case self.PROPAGATE__SKIP:
                return "ps"
            case self.PROPAGATE__NOT_A_WORD:
                return "pn"
            case self.PROPAGATE__TIME:
                return "pt"
            case _:
                return None

    @classmethod
    def from_code(cls, code: str) -> "AnswerType":
        """Get answer type from its database code."""
        for answer_type in cls:
            if answer_type.to_code() == code:
                return answer_type

        message = f"Unknown answer type code `{code}`."
        raise ValueError(message)


def compute_lexicon_rate(
    data: list[tuple[datetime, int]], precision: int = 100
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


def _fit_logistic(
    ranks: list[int], labels: list[int]
) -> tuple[float, float, float]:
    """Fit 3-parameter logistic model π_i = c · σ(a · log(rank) + b).

    :param ranks: frequency ranks (1-indexed, 1 = most frequent)
    :param labels: 1 if unknown, 0 if known
    :return: fitted parameters (a, b, c)
    """
    x: np.ndarray = np.log(np.array(ranks, dtype=float))
    y: np.ndarray = np.array(labels, dtype=float)

    def neg_log_likelihood(params: np.ndarray) -> float:
        # t → a = exp(t) > 0: monotonicity (rarer words more likely unknown).
        t, b = params
        a: float = float(np.exp(t))
        pi: np.ndarray = np.clip(expit(a * x + b), 1e-10, 1.0 - 1e-10)
        return float(-np.sum(y * np.log(pi) + (1.0 - y) * np.log(1.0 - pi)))

    result = minimize(
        neg_log_likelihood,
        x0=np.array([0.0, -5.0]),  # t=0 → a=1
        method="Nelder-Mead",
        options={"xatol": 1e-4, "fatol": 1e-4},
    )
    t, b = result.x
    return float(np.exp(t)), float(b), 1.0


def _predict(a: float, b: float, c: float, rank: int) -> float:
    """Predict probability of being unknown at the given frequency rank."""
    try:
        return c / (1.0 + math.exp(-(a * math.log(rank) + b)))
    except OverflowError:
        return 0.0


def rate(ratio: float) -> float | None:
    """Compute Emmio lexicon rating.

    Rate is just a more readable representation of the ratio of unknown words.

    :param ratio: the ratio of unknown words to all words in some text, corpus
        of texts or some random sample of text or corpus of texts
    :return: rating or None if ratio is 0
    """
    if not ratio:
        return None
    return -math.log2(ratio)


class WordSelection(Enum):
    """How to select words for checking."""

    ARBITRARY = "arbitrary"
    """Select words arbitrarily."""

    RANDOM_WORD_FROM_LIST = "random"
    """Select a word randomly from a list of all unique words.

    Note, that is not the same as selecting a random word from the whole corpus
    of texts.
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

    def model_dump_json(self, *args: Any, **kwargs: Any) -> str:
        """Serialize to JSON string.

        TODO(enzet): this field order is such for historical reasons. We should
        change it in the future.
        """
        order: list[str] = [
            "word",
            "response",
            "answer_type",
            "to_skip",
            "time",
        ]
        data: dict = super().model_dump(mode="json", exclude_none=True)
        # `user_answer` is the default answer type: skip it, as it was absent
        # in records created before the field was introduced.
        for record in data["records"]:
            if record.get("answer_type") == AnswerType.USER_ANSWER.value:
                del record["answer_type"]
        records: list[dict[str, Any]] = [
            OrderedDict((key, record[key]) for key in order if key in record)
            for record in data["records"]
        ]
        return json.dumps(
            {"records": records, "sessions": data["sessions"]},
            ensure_ascii=False,
            *args,  # noqa: B026
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

    user_id: str = ""
    """Login of the user that owns this lexicon."""

    saved_records: int = 0
    """Number of records already stored in the database."""

    saved_sessions: int = 0
    """Number of sessions already stored in the database."""

    @classmethod
    def from_config(
        cls, path: Path, id_: str, config: LexiconConfig, user_id: str
    ) -> Self:
        """Initialize lexicon.

        Records and sessions are loaded from the PostgreSQL database; the
        lexicon is created on first write if it is not there yet.

        :param path: path to the directory with lexicon files
        :param id_: unique lexicon identifier
        :param config: lexicon configuration
        :param user_id: login of the user that owns this lexicon
        """
        language: Language = Language.from_code(config.language)

        file_path: Path = path / config.file_name

        words: dict[str, WordKnowledge] = {}
        dates: list[datetime] = []
        responses: list[int] = []
        start: datetime | None = None
        finish: datetime | None = None

        logger.debug("Loading lexicon `%s` from database...", id_)
        record_rows, session_rows = postgres.load_lexicon(user_id, id_)

        log: LexiconLog = LexiconLog(
            records=[
                LexiconLogRecord(
                    word=word,
                    response=LexiconResponse.from_code(response),
                    answer_type=(
                        AnswerType.from_code((extra or {})["at"])
                        if "at" in (extra or {})
                        else AnswerType.USER_ANSWER
                    ),
                    to_skip=(extra or {}).get("sk"),
                    time=response_time,
                    request_time=(
                        datetime.fromisoformat((extra or {})["rt"])
                        if "rt" in (extra or {})
                        else None
                    ),
                )
                for (word, response, response_time, extra) in record_rows
            ],
            sessions=[
                LexiconLogSession(start=session_start, end=session_end)
                for (session_start, session_end) in session_rows
            ],
        )

        for record in log.records:
            words[record.word] = WordKnowledge(record.response, record.to_skip)

        # Fill data.

        for record in log.records:
            if record.response in [LexiconResponse.KNOW, LexiconResponse.DONT]:
                dates.append(record.time)
                responses.append(
                    1 if record.response == LexiconResponse.KNOW else 0
                )

                if start is None:
                    start = record.time
                finish = record.time

        lexicon = cls(
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
            user_id,
        )
        lexicon.saved_records = len(log.records)
        lexicon.saved_sessions = len(log.sessions)
        return lexicon

    def dump_json(self) -> str:
        """Serialize lexicon to a JSON string."""
        return self.log.model_dump_json(indent=4)

    @override
    def write(self) -> None:
        """Append new records and sessions to the database."""

        records: list[postgres.LexiconRecordRow] = []
        for record in self.log.records[self.saved_records :]:
            extra: dict = {}
            if record.answer_type and (code := record.answer_type.to_code()):
                extra["at"] = code
            if record.to_skip is not None:
                extra["sk"] = record.to_skip
            if record.request_time is not None:
                extra["rt"] = record.request_time.isoformat()
            records.append(
                (
                    record.word,
                    record.response.to_code(),
                    record.time,
                    extra or None,
                )
            )
        sessions: list[postgres.LexiconSessionRow] = [
            (session.start, session.end)
            for session in self.log.sessions[self.saved_sessions :]
        ]
        postgres.save_lexicon(
            self.user_id, self.id_, self.language.get_code(), records, sessions
        )
        self.saved_records = len(self.log.records)
        self.saved_sessions = len(self.log.sessions)

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
        interface: Interface,
        response: LexiconResponse,
        *,
        to_skip: bool | None,
        request_time: datetime | None,
        time: datetime | None = None,
        answer_type: AnswerType = AnswerType.UNKNOWN,
    ) -> None:
        """Register user's response.

        :param word: the question id that user was responded to
        :param interface: interface for communicating with the user
        :param response: response type
        :param to_skip: skip this word in the future
        :param request_time: time of the question
        :param time: time of the response
        :param answer_type: is it was a user answer or the previous answer was
            used
        """
        if not time:
            time = datetime.now(UTC)

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

        # If user had no interaction with the word, print the reason it was
        # registered.
        if not answer_type.is_user_answer():
            interface.print(
                Colorized(f"[{answer_type}] {response} {word}", "#AAAAAA")
            )

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
        # TODO(enzet): rename.

        dates_and_responses: list[tuple[datetime, int]] = list(
            zip(self.dates, self.responses, strict=False)
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
        # TODO(enzet): rewrite, the implementation is too resource-consuming.

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

        :param frequency_list: sort words using this list
        """
        result: list[str] = []

        for word in sorted(
            self.words.keys(),
            key=lambda word: -frequency_list.get_occurrences(word),
        ):
            word_knowledge: WordKnowledge = self.words[word]
            if word_knowledge.knowing == LexiconResponse.DONT:
                result.append(word)

        return result

    def get_question(
        self,
        word: str,
        sentences_data: SentencesData,
        sentences_usage_configs: list[SentencesUsageConfig],
    ) -> list[Element]:
        """Get question text for picked word to ask user."""

        result: list[Element] = [Block(Colorized(word, "bold"), (0, 0, 0, 4))]
        if self.has(word):
            result.append(
                Text(
                    Colorized(
                        f"Last response was: {self.get(word).get_message()}.",
                        "#AAAAAA",
                    )
                )
            )

        if sentences_usage_configs and (
            sentence_translations := sentences_data.get(
                word, sentences_usage_configs
            )
        ):
            sentence: Sentence = random.choice(sentence_translations).sentence
            splitted: list[tuple[str, SentenceElement]] = sentence.get_words(
                self.language
            )
            text: Text = Text()
            for part, type_ in splitted:
                if (
                    type_ == SentenceElement.WORD
                    and self.language.normalize(part) == word
                ):
                    text.add(Formatted(part, "bold"))
                else:
                    text.add(part)
            example: Text = (
                Text().add(Colorized("Usage example: ", "#AAAAAA")).add(text)
            )
            result.append(example)

        return result

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

    def __len__(self) -> int:
        return len(self.words)

    def __repr__(self) -> str:
        return f"<User lexicon {self.language.get_name()}>"

    def get_user_records(self, word: str) -> list[LexiconLogRecord]:
        """Get all records for a specific word."""

        return [
            record
            for record in self.log.records
            if (
                record.word == word
                and record.answer_type == AnswerType.USER_ANSWER
            )
        ]

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


MIN_SIZE_TESTED_RANKS = 10
MIN_R_BOOTS = 10
MIN_N_UNKNOWN = 5


@dataclass
class LexiconChecker:
    """Checker for the lexicon."""

    interface: Interface
    lexicon: Lexicon

    dictionaries: DictionaryCollection
    sentences_data: SentencesData
    sentences_usage_configs: list[SentencesUsageConfig]
    skip_known: bool = False
    skip_unknown: bool = False

    async def ask(
        self, word: str
    ) -> tuple[bool | None, LexiconResponse | None, Dictionary | None]:
        """Ask user if the word is known.

        :return: tuple of (skip in the future, response, dictionary)
        """

        # TODO(enzet): get definitions languages from user settings.
        definitions_languages: list[Language] = [
            KnownLanguages.ENGLISH,
            KnownLanguages.RUSSIAN,
        ]

        for element in self.lexicon.get_question(
            word, self.sentences_data, self.sentences_usage_configs
        ):
            self.interface.print(element)

        start_time: datetime = datetime.now(UTC)

        translation: list[Element] | None = await self.dictionaries.to_text(
            word, self.lexicon.language, definitions_languages
        )
        if translation is not None and translation:
            self.interface.button("Show translation")
            for element in translation:
                self.interface.print(element)

        answer: str = self.interface.choice(
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
                self.lexicon.write()
                return False, None, None
            case _:
                response = LexiconResponse.DONT

        self.interface.print(Colorized(response.get_message(), "#AAAAAA"))

        if skip_in_future is None:
            if response == LexiconResponse.KNOW:
                skip_in_future = self.skip_known
            elif response == LexiconResponse.DONT:
                skip_in_future = self.skip_unknown

        self.lexicon.register(
            word,
            self.interface,
            response,
            to_skip=skip_in_future,
            request_time=start_time,
            answer_type=AnswerType.USER_ANSWER,
        )
        return skip_in_future, response, None

    async def binary_search(self, frequency_list: FrequencyList) -> None:
        """Try to find position of the balanced word.

        This is an experimental function. It's result has meaning only if it is
        repeated many times and the average is computed.

        Firstly, we try the random word of the frequency list. If it is known,
        we try the word in the middle of the right half, else we try the word
        in the middle of the left half.
        """
        left_border, right_border = 0, int((len(frequency_list) - 1) / 2)
        while True:
            index: int = int((left_border + right_border) / 2)
            picked_word, occurrences = frequency_list.get_word_by_index(index)
            _, response, _ = await self.ask(picked_word)
            if not response:
                break
            if response == LexiconResponse.KNOW:
                left_border = index
            elif response == LexiconResponse.DONT:
                right_border = index
            else:
                left_border += 2
            not_known: int = 0
            for i in range(index, len(frequency_list) - 1):
                _, occurrences = frequency_list.get_word_by_index(i)
                not_known += occurrences
            self.lexicon.write()

    async def check(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at_wrong: int | None,
    ) -> None:
        """Check lexicon."""
        if self.lexicon.config.selection == LexiconSelection.FREQUENCY:
            await self.check_frequency(
                other_lexicons,
                frequency_list,
                stop_at=None,
                log_type="frequency",
                stop_at_wrong=stop_at_wrong,
            )
        elif self.lexicon.config.selection == LexiconSelection.LOGISTIC:
            await self.check_logistic(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )
        elif self.lexicon.config.selection == LexiconSelection.STRATIFIED:
            await self.check_stratified(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )

    async def check_frequency(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        log_type: str,
        stop_at_wrong: int | None,
    ) -> str:
        """Check current user vocabulary.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: list of the words with frequency to check
        :param stop_at: stop after a number of actions
        :param log_type: the method of picking words
        :param stop_at_wrong: stop after a number of unknown words

        :return: exit code
        """

        session: LexiconLogSession = LexiconLogSession(start=datetime.now(UTC))

        # Actions during current session:
        actions: int = 0
        wrong_answers: int = 0

        checked_in_session: set[str] = set()

        exit_code: str = "quit"

        most_frequent_index: int = 0

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
                picked_word, _ = frequency_list.get_word_by_index(
                    most_frequent_index
                )
                most_frequent_index += 1
                if self.lexicon.has(picked_word):
                    continue
                items: list[DictionaryItem] = await self.dictionaries.get_items(
                    picked_word, self.lexicon.language
                )
                if not items or items[0].is_not_common(self.lexicon.language):
                    continue
            else:
                message = f"Unknown lexicon log type `{log_type}."
                raise ValueError(message)

            if picked_word:
                checked_in_session.add(picked_word)

            if self.do_skip(picked_word, other_lexicons):
                continue

            _, response, _ = await self.ask(picked_word)
            actions += 1
            if response == LexiconResponse.DONT:
                wrong_answers += 1

            for element in self.lexicon.get_statistics():
                self.interface.print(element)

            if not response:
                exit_code = "quit"
                break

            if stop_at and actions >= stop_at:
                exit_code = "limit"
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                exit_code = "limit"
                break

        session.end_session(datetime.now(UTC))
        self.lexicon.log.sessions.append(session)
        self.lexicon.write()

        return exit_code

    def estimate_r(
        self, frequency_list: FrequencyList, a: float, b: float, c: float
    ) -> float | None:
        """Estimate r using the logistic model.

        Computes θ̂ = Σ_{i∈S} p_i X_i  +  Σ_{i∈U} p_i · π̂_i and returns
        r̂ = -log₂(θ̂). Returns None if there is not enough data to fit the
        model.

        :param frequency_list: frequency list providing p_i values
        :return: estimated r, or None if the model cannot be fitted
        """
        total: int = frequency_list.get_all_occurrences()
        words: list[str] = frequency_list.get_words()

        tested_ranks: list[int] = []
        tested_labels: list[int] = []
        theta_s: float = 0.0

        for rank, word in enumerate(words, start=1):
            if not self.lexicon.has(word):
                continue
            p_i: float = frequency_list.get_occurrences(word) / total
            response: LexiconResponse = self.lexicon.get(word)
            if response == LexiconResponse.KNOW:
                tested_ranks.append(rank)
                tested_labels.append(0)
            elif response == LexiconResponse.DONT:
                tested_ranks.append(rank)
                tested_labels.append(1)
                theta_s += p_i

        n_unknown: int = sum(tested_labels)
        if (
            len(tested_ranks) < MIN_SIZE_TESTED_RANKS
            or n_unknown < MIN_N_UNKNOWN
        ):
            return None

        theta_u: float = sum(
            frequency_list.get_occurrences(word)
            / total
            * _predict(a, b, c, rank)
            for rank, word in enumerate(words, start=1)
            if not self.lexicon.has(word)
        )

        theta: float = theta_s + theta_u
        if theta <= 0.0:
            return None
        return -math.log2(theta)

    def estimate_r_with_sd(
        self, frequency_list: FrequencyList, n_bootstrap: int = 200
    ) -> tuple[float, float] | None:
        """Estimate r and its standard deviation via bootstrap resampling.

        The uncertainty in r̂ comes entirely from uncertainty in the logistic
        model parameters (a, b, c), which determine θ̂_u (the contribution of
        untested words). The contribution θ_s from tested words is an exact
        observation, not a model estimate, so it is held fixed across bootstrap
        iterations.

        :param frequency_list: frequency list providing p_i values
        :param n_bootstrap: number of bootstrap resamples
        :return: (r_hat, sd_r_hat), or None if not enough data
        """
        total: int = frequency_list.get_all_occurrences()
        words: list[str] = frequency_list.get_words()

        tested_ranks: list[int] = []
        tested_labels: list[int] = []
        theta_s: float = 0.0

        for rank, word in enumerate(words, start=1):
            if not self.lexicon.has(word):
                continue
            p_i: float = frequency_list.get_occurrences(word) / total
            response: LexiconResponse = self.lexicon.get(word)
            if response == LexiconResponse.KNOW:
                tested_ranks.append(rank)
                tested_labels.append(0)
            elif response == LexiconResponse.DONT:
                tested_ranks.append(rank)
                tested_labels.append(1)
                theta_s += p_i

        n_unknown: int = sum(tested_labels)
        if (
            len(tested_ranks) < MIN_SIZE_TESTED_RANKS
            or n_unknown < MIN_N_UNKNOWN
        ):
            return None

        untested: list[tuple[int, float]] = [
            (rank, frequency_list.get_occurrences(word) / total)
            for rank, word in enumerate(words, start=1)
            if not self.lexicon.has(word)
        ]

        def theta_u_from_params(a: float, b: float, c: float) -> float:
            return sum(p_i * _predict(a, b, c, rank) for rank, p_i in untested)

        # Point estimate.
        a, b, c = _fit_logistic(tested_ranks, tested_labels)
        theta: float = theta_s + theta_u_from_params(a, b, c)
        if theta <= 0.0:
            return None
        r_hat: float = -math.log2(theta)

        # Bootstrap: resample (rank, label) pairs to estimate SD of r_hat.
        ranks_arr: np.ndarray = np.array(tested_ranks)
        labels_arr: np.ndarray = np.array(tested_labels)
        n: int = len(tested_ranks)
        rng = np.random.default_rng()
        r_boots: list[float] = []

        for _ in range(n_bootstrap):
            idx = rng.integers(0, n, size=n)
            boot_ranks: list[int] = cast("list[int]", ranks_arr[idx].tolist())
            boot_labels: list[int] = cast("list[int]", labels_arr[idx].tolist())
            if not any(label == 0 for label in boot_labels) or not any(
                label == 1 for label in boot_labels
            ):
                continue
            try:
                a_b, b_b, c_b = _fit_logistic(boot_ranks, boot_labels)
            except (ValueError, RuntimeError):
                continue
            theta_boot: float = theta_s + theta_u_from_params(a_b, b_b, c_b)
            if theta_boot > 0.0:
                r_boots.append(-math.log2(theta_boot))

        if len(r_boots) < MIN_R_BOOTS:
            return None

        return r_hat, float(np.std(r_boots, ddof=1))

    async def check_logistic(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
    ) -> str:
        """Check vocabulary using logistic model with adaptive sampling.

        Implements Method 2: fit a 3-parameter logistic model to the tested
        set S, then select words that maximise variance reduction of θ̂.
        Falls back to frequency-weighted random sampling until enough data
        exists to fit the model.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: frequency list to use for word selection
        :param stop_at: stop after this many user interactions
        :param stop_at_wrong: stop after this many unknown words found
        :return: exit code
        """
        session: LexiconLogSession = LexiconLogSession(start=datetime.now(UTC))
        actions: int = 0
        wrong_answers: int = 0
        exit_code: str = "quit"

        total: int = frequency_list.get_all_occurrences()
        words: list[str] = frequency_list.get_words()

        while True:
            # Build S: collect tested (rank, label) pairs, label=1 if unknown.
            unknown_ranks: list[int] = []
            tested_ranks: list[int] = []
            tested_labels: list[int] = []
            for rank, word in enumerate(words, start=1):
                if not self.lexicon.has(word):
                    continue
                response: LexiconResponse | None = self.lexicon.get(word)
                if response == LexiconResponse.KNOW:
                    tested_ranks.append(rank)
                    tested_labels.append(0)
                elif response == LexiconResponse.DONT:
                    tested_ranks.append(rank)
                    tested_labels.append(1)
                    unknown_ranks.append(rank)

            # Fit logistic model when there is enough data.
            params: tuple[float, float, float] | None = None
            if (
                len(unknown_ranks) >= MIN_N_UNKNOWN
                and len(tested_ranks) >= MIN_SIZE_TESTED_RANKS
            ):
                params = _fit_logistic(tested_ranks, tested_labels)
                a, b, c = params
                logger.info(
                    "model: a=%.3f b=%.3f i*=%.0f | "
                    "π(1k)=%.3f π(10k)=%.3f π(100k)=%.3f",
                    a,
                    b,
                    math.exp(-b / a),
                    _predict(a, b, c, 1_000),
                    _predict(a, b, c, 10_000),
                    _predict(a, b, c, 100_000),
                )
                if r_val := self.estimate_r(frequency_list, a, b, c):
                    logger.info("r = %.2f", r_val)

            # Select next word.
            untested: list[tuple[int, str]] = [
                (rank, word)
                for rank, word in enumerate(words, start=1)
                if not self.lexicon.has(word)
            ]
            picked_word: str | None = None
            picked_rank: int | None = None

            if params is not None:
                # Exploit: pick the untested word with highest score.
                best_score: float = -1.0
                for rank, word in untested:
                    p_i: float = frequency_list.get_occurrences(word) / total
                    pi_i: float = _predict(a, b, c, rank)
                    score: float = p_i**2 * pi_i * (1.0 - pi_i)
                    if score > best_score:
                        best_score = score
                        picked_word = word
                        picked_rank = rank
            # Explore: log-uniform random rank until model is ready.
            elif untested:
                max_rank: int = untested[-1][0]
                target: int = max(1, int(max_rank ** random.random()))
                picked_rank, picked_word = min(
                    untested, key=lambda rw: abs(rw[0] - target)
                )

            if picked_word is None:
                break

            logger.info("picked rank: %d", picked_rank)

            if self.do_skip(picked_word, other_lexicons):
                continue

            _, response, _ = await self.ask(picked_word)
            actions += 1
            if response == LexiconResponse.DONT:
                wrong_answers += 1

            for element in self.lexicon.get_statistics():
                self.interface.print(element)

            if not response:
                exit_code = "quit"
                break

            if stop_at and actions >= stop_at:
                exit_code = "limit"
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                exit_code = "limit"
                break

        session.end_session(datetime.now(UTC))
        self.lexicon.log.sessions.append(session)
        self.lexicon.write()

        return exit_code

    async def check_stratified(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
        n_strata: int = 10,
    ) -> str:
        """Check vocabulary using stratified frequency-weighted random sampling.

        Implements SFWR: divides the frequency list into K log-uniform strata
        B_k = {i : N^((k-1)/K) <= rank < N^(k/K)} and samples adaptively,
        always querying the stratum with the highest current variance
        contribution P_k^2 * theta_k * (1 - theta_k).

        Within each stratum theta_k is estimated as the frequency-weighted
        proportion of unknown words among tested words; strata with no tested
        words use a 0.5 prior.  The combined estimator is the
        Horvitz-Thompson estimate theta = sum_k P_k * theta_k.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: frequency list used for word selection
        :param stop_at: stop after this many user interactions
        :param stop_at_wrong: stop after this many unknown words found
        :param n_strata: number of log-uniform strata K
        :return: exit code
        """
        session: LexiconLogSession = LexiconLogSession(start=datetime.now(UTC))
        actions: int = 0
        wrong_answers: int = 0
        exit_code: str = "quit"

        total: int = frequency_list.get_all_occurrences()
        words: list[str] = frequency_list.get_words()
        n: int = len(words)

        if n == 0:
            return exit_code

        def stratum_of(rank: int) -> int:
            """Map a 1-based rank to a stratum index in [0, n_strata)."""
            k = int(n_strata * math.log(rank) / math.log(n))
            return min(max(k, 0), n_strata - 1)

        while True:
            stratum_p_total: list[float] = [0.0] * n_strata
            stratum_p_unknown: list[float] = [0.0] * n_strata
            stratum_p_tested: list[float] = [0.0] * n_strata
            untested_by_stratum: list[list[tuple[int, str]]] = [
                [] for _ in range(n_strata)
            ]

            for rank, word in enumerate(words, start=1):
                k: int = stratum_of(rank)
                p_i: float = frequency_list.get_occurrences(word) / total
                stratum_p_total[k] += p_i
                if self.lexicon.has(word):
                    known: LexiconResponse | None = self.lexicon.get(word)
                    if known in (LexiconResponse.KNOW, LexiconResponse.DONT):
                        stratum_p_tested[k] += p_i
                        if known == LexiconResponse.DONT:
                            stratum_p_unknown[k] += p_i
                else:
                    untested_by_stratum[k].append((rank, word))

            # Estimate theta_k for each stratum.
            theta_k: list[float] = [
                (
                    stratum_p_unknown[k] / stratum_p_tested[k]
                    if stratum_p_tested[k] > 0.0
                    else 0.5
                )
                for k in range(n_strata)
            ]

            # Compute combined estimator and log it.
            theta: float = sum(
                stratum_p_total[k] * theta_k[k] for k in range(n_strata)
            )
            if theta > 0.0:
                logger.info(
                    "r = %.2f | theta_k: %s",
                    -math.log2(theta),
                    " ".join(f"{theta_k[k]:.2f}" for k in range(n_strata)),
                )

            # Pick stratum with max variance contribution among those with
            # untested words.
            best_k: int | None = None
            best_score: float = -1.0
            for k in range(n_strata):
                if not untested_by_stratum[k]:
                    continue
                score: float = (
                    stratum_p_total[k] ** 2 * theta_k[k] * (1.0 - theta_k[k])
                )
                if score > best_score:
                    best_score = score
                    best_k = k

            if best_k is None:
                break  # All words tested.

            # Within the stratum, pick the highest-frequency untested word.
            picked_rank, picked_word = min(
                untested_by_stratum[best_k], key=lambda rw: rw[0]
            )
            logger.info("stratum %d, picked rank %d", best_k, picked_rank)

            if self.do_skip(picked_word, other_lexicons):
                continue

            _, answer, _ = await self.ask(picked_word)
            actions += 1
            if answer == LexiconResponse.DONT:
                wrong_answers += 1

            for element in self.lexicon.get_statistics():
                self.interface.print(element)

            if not answer:
                exit_code = "quit"
                break

            if stop_at and actions >= stop_at:
                exit_code = "limit"
                break

            if stop_at_wrong and wrong_answers >= stop_at_wrong:
                exit_code = "limit"
                break

        session.end_session(datetime.now(UTC))
        self.lexicon.log.sessions.append(session)
        self.lexicon.write()

        return exit_code

    def do_skip(
        self, picked_word: str, other_lexicons: list["Lexicon"]
    ) -> bool:
        """Check whether the word should be skipped.

        :param picked_word: word to check
        :param other_lexicons: other user lexicons of the same language

        :return: whether the word should be skipped
        """
        lexicon_records: list[LexiconLogRecord] = []
        for lexicon in other_lexicons:
            if lexicon.has(picked_word):
                lexicon_records += lexicon.get_records(picked_word)

        lexicon_records = sorted(
            lexicon_records, key=lambda record: record.time
        )

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
                or (
                    self.skip_known
                    and last_record.response == LexiconResponse.KNOW
                )
                or (
                    self.skip_unknown
                    and last_record.response == LexiconResponse.DONT
                )
            ):
                self.lexicon.register(
                    picked_word,
                    self.interface,
                    last_record.response,
                    to_skip=skip_marker,
                    request_time=None,
                    answer_type=AnswerType.PROPAGATE__SKIP,
                )
                return True

            if last_record.response == LexiconResponse.NOT_A_WORD:
                self.lexicon.register(
                    picked_word,
                    self.interface,
                    LexiconResponse.NOT_A_WORD,
                    to_skip=None,
                    request_time=None,
                    answer_type=AnswerType.PROPAGATE__NOT_A_WORD,
                )
                return True

            was_answered_recently: bool = False

            for record in reversed(self.lexicon.log.records):
                delta = datetime.now(UTC) - record.time
                if delta.days > 30:
                    break
                if (
                    picked_word == record.word
                    and record.answer_type == AnswerType.USER_ANSWER
                ):
                    was_answered_recently = True
                    break

            if was_answered_recently:
                self.lexicon.register(
                    picked_word,
                    self.interface,
                    last_record.response,
                    to_skip=None,
                    request_time=None,
                    answer_type=AnswerType.PROPAGATE__TIME,
                )
                return True

        # Mark word as "not a word" if it contains symbols that do not appear
        # in language.

        is_foreign: bool = False
        if (symbols := self.lexicon.language.get_symbols()) and symbols:
            for symbol in picked_word:
                if symbol not in symbols:
                    is_foreign = True
                    break

        if is_foreign:
            self.lexicon.register(
                picked_word,
                self.interface,
                LexiconResponse.NOT_A_WORD,
                to_skip=None,
                request_time=None,
                answer_type=AnswerType.ASSUME__NOT_A_WORD__ALPHABET,
            )
            return True

        return False
