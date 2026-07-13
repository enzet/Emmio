"""Core functionality for lexicon."""

import bisect
import json
import logging
import math
import random
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Self, cast, override

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


_SAMPLE_ATTEMPTS: int = 100
"""Random draws to try before falling back to a scan for an unanswered word."""


WordStates = dict[str, tuple[str | None, bool | None]]
"""Per-word latest state: word → (response code, to_skip).

Mirrors `postgres.get_language_word_states`. The response code is the
single-character `LexiconResponse` code (e.g. `K`, `D`); `None` means the word
has no recorded response.
"""


def select_next_word(
    frequency_list: FrequencyList,
    exclude: set[str],
    selection: str,
    states: WordStates | None = None,
) -> str | None:
    """Pick the next word to check, honoring the lexicon's selection strategy.

    This is the selection step lifted out of the interactive checking loop, so
    it can be driven by a stateless request without touching any user
    interface. The strategy must match how the lexicon's data was collected;
    serving words by the wrong strategy biases the rate estimate.

    The model-based strategies (`logistic`, `threshold`, `stratified`) need the
    learner's answered words to fit their model; pass them via `states`. Their
    selection logic mirrors the interactive `check_logistic`/`check_stratified`
    methods — keep the two in sync.

    :param frequency_list: source of candidate words
    :param exclude: words to skip (e.g. flagged to skip or answered recently);
        a frequency lexicon re-samples words over time, so this is *not* every
        word ever answered
    :param selection: the lexicon's stored selection strategy
    :param states: per-word state, required by the model-based strategies
    :return: the next word, or None if every candidate is excluded
    :raises NotImplementedError: for strategies not served over the API
    """
    return create_selector(frequency_list, selection, states).next_word(exclude)


def _optimal_threshold(paired: list[tuple[int, int]]) -> int:
    """Find the rank i* that minimises step-function misclassification.

    Sweep a split point over the tested words sorted by rank: the first j
    words are predicted known, the rest unknown; errors(j) = (unknown among
    first j) + (known among rest). This is the decision-stump / OT boundary.

    :param paired: tested (rank, label) pairs sorted by rank, 1 = unknown
    :return: the boundary rank i*; words with rank above it are predicted
        unknown
    """
    known_suffix: int = sum(1 for _, label in paired if label == 0)
    unknown_prefix: int = 0
    best_j: int = 0
    best_err: int = known_suffix
    for j in range(1, len(paired) + 1):
        if paired[j - 1][1] == 1:
            unknown_prefix += 1
        else:
            known_suffix -= 1
        err: int = unknown_prefix + known_suffix
        if err < best_err:
            best_err = err
            best_j = j

    if best_j == 0:
        return paired[0][0]
    if best_j == len(paired):
        return paired[-1][0]
    return (paired[best_j - 1][0] + paired[best_j][0]) // 2


# Number of log-uniform strata used by the stratified (SFWR) strategy.
DEFAULT_N_STRATA: int = 10


def stratum_of_rank(
    rank: int, size: int, n_strata: int = DEFAULT_N_STRATA
) -> int:
    """Map a 1-based frequency rank to its log-uniform stratum index.

    The single place the stratum boundary formula lives: selection, estimation
    and the API's per-word reporting all go through it.

    :param rank: 1-based position in the frequency list
    :param size: total number of words in the frequency list
    :param n_strata: number of log-uniform strata K
    :return: stratum index in [0, n_strata)
    """
    if size <= 1:
        return 0
    k: int = int(n_strata * math.log(rank) / math.log(size))
    return min(max(k, 0), n_strata - 1)


def _shares_by_rank(frequency_list: FrequencyList) -> np.ndarray:
    """Get frequency shares p_i indexed by rank − 1, memoized on the list."""
    key: str = "shares_by_rank"
    if key not in frequency_list.derived:
        total: int = frequency_list.get_all_occurrences()
        frequency_list.derived[key] = (
            np.array(
                [
                    frequency_list.get_occurrences(word)
                    for word in frequency_list.get_words()
                ],
                dtype=float,
            )
            / total
        )
    return frequency_list.derived[key]


def _squared_shares_by_rank(frequency_list: FrequencyList) -> np.ndarray:
    """Get squared frequency shares p_i² by rank − 1, memoized on the list."""
    key: str = "squared_shares_by_rank"
    if key not in frequency_list.derived:
        frequency_list.derived[key] = _shares_by_rank(frequency_list) ** 2
    return frequency_list.derived[key]


def _log_ranks(frequency_list: FrequencyList) -> np.ndarray:
    """Get log(rank) values indexed by rank − 1, memoized on the list."""
    key: str = "log_ranks"
    if key not in frequency_list.derived:
        frequency_list.derived[key] = np.log(
            np.arange(1, len(frequency_list) + 1, dtype=float)
        )
    return frequency_list.derived[key]


def _stratum_bounds(
    frequency_list: FrequencyList, n_strata: int
) -> list[tuple[int, int]]:
    """Get per-stratum rank ranges, memoized on the list.

    :return: `[lo, hi)` 1-based rank ranges, one per stratum; consistent with
        `stratum_of_rank` by construction (its value is nondecreasing in rank,
        so each stratum is one contiguous range, found by bisection)
    """
    key: tuple[str, int] = ("stratum_bounds", n_strata)
    if key not in frequency_list.derived:
        n: int = len(frequency_list)
        bounds: list[tuple[int, int]] = []
        lo: int = 1
        for k in range(n_strata):
            hi: int = (
                bisect.bisect_right(
                    range(1, n + 1),
                    k,
                    key=lambda rank: stratum_of_rank(rank, n, n_strata),
                )
                + 1
            )
            bounds.append((lo, hi))
            lo = hi
        frequency_list.derived[key] = bounds
    return frequency_list.derived[key]


def _stratum_masses(
    frequency_list: FrequencyList, n_strata: int
) -> list[float]:
    """Get per-stratum total frequency mass P_k, memoized on the list."""
    key: tuple[str, int] = ("stratum_masses", n_strata)
    if key not in frequency_list.derived:
        total: int = frequency_list.get_all_occurrences()
        frequency_list.derived[key] = [
            frequency_list.get_range_occurrences(lo - 1, hi - 1) / total
            for lo, hi in _stratum_bounds(frequency_list, n_strata)
        ]
    return frequency_list.derived[key]


def _state_category(code: str | None) -> int:
    """Categorize a response code for selection bookkeeping.

    :param code: single-character `LexiconResponse` code, or None
    :return: 0 for tested known, 1 for tested unknown, 2 for resolved (has a
        state, but is neither tested nor a candidate: not a word, proper noun,
        or an explicit state without a response)
    """
    if code == "K":
        return 0
    if code == "D":
        return 1
    return 2


class WordSelector(ABC):
    """Working memory of one word-selection strategy over one frequency list.

    Built once from the current per-word states in O(answered words), then
    kept in sync through `record` as answers arrive, so each `next_word` call
    avoids rescanning the whole list. The selector is only the selection
    policy's working memory: answers themselves are ground truth persisted
    elsewhere, so a lost or stale selector can always be rebuilt, at worst
    costing one slightly suboptimal draw.
    """

    @abstractmethod
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        """Pick the next word to ask.

        :param exclude: words to skip for this draw only (e.g. queued on the
            client); permanent exclusions go through `record`
        :return: the next word, or None if every candidate is excluded
        """

    @abstractmethod
    def record(self, word: str, response_code: str | None) -> None:
        """Update the working memory with an answered word.

        :param word: the answered word
        :param response_code: single-character `LexiconResponse` code, or None
            for a state without a response
        """


class _SampledSelector(WordSelector):
    """Memoryless strategy (FWR, uniform): draws ignore recorded answers.

    Answered words are deliberately re-drawn over time — the caller decides
    whether to present or propagate them — so `record` is a no-op.
    """

    def __init__(
        self, frequency_list: FrequencyList, draw: Callable[[], tuple[str, int]]
    ) -> None:
        self._frequency_list: FrequencyList = frequency_list
        self._draw: Callable[[], tuple[str, int]] = draw

    @override
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        for _ in range(_SAMPLE_ATTEMPTS):
            word, _occurrences = self._draw()
            if word not in exclude:
                return word
        # Draws keep missing: scan for any selectable word.
        for word in self._frequency_list.get_words():
            if word not in exclude:
                return word
        return None

    @override
    def record(self, word: str, response_code: str | None) -> None:
        """Do nothing: memoryless draws do not depend on answers."""


class TopSelector(WordSelector):
    """Deterministic walk down the frequency list (`top` strategy).

    The working memory is a cursor: the first rank that may still be
    unanswered. Unlike the model-based strategies it is seeded with the words
    answered in *this* lexicon only, so a word answered in a sibling lexicon
    is still drawn once and gets its answer propagated by the caller.
    """

    def __init__(
        self, frequency_list: FrequencyList, answered: set[str]
    ) -> None:
        self._words: list[str] = frequency_list.get_words()
        self._answered: set[str] = answered
        self._cursor: int = 0

    @override
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        words: list[str] = self._words
        while self._cursor < len(words) and words[self._cursor] in (
            self._answered
        ):
            self._cursor += 1
        for index in range(self._cursor, len(words)):
            word: str = words[index]
            if word not in self._answered and word not in exclude:
                return word
        return None

    @override
    def record(self, word: str, response_code: str | None) -> None:
        self._answered.add(word)


class _RankedSelector(WordSelector):
    """Base of the model-based strategies, tracking word states by rank.

    A word answered `KNOW`/`DONT` (anywhere in the same language) is tested;
    a word answered otherwise (e.g. not-a-word, proper noun) is resolved and
    so is neither tested nor a candidate; a word without a state is a
    candidate. Subclasses keep their sufficient statistics up to date through
    the `_on_state_change` hook.
    """

    def __init__(self, frequency_list: FrequencyList) -> None:
        self._frequency_list: FrequencyList = frequency_list
        self._words: list[str] = frequency_list.get_words()
        self._n: int = len(self._words)
        self._codes: dict[str, str | None] = {}

    def _ingest(self, states: WordStates) -> None:
        """Replay the initial per-word states through `record`."""
        for word, (code, _to_skip) in states.items():
            self.record(word, code)

    @override
    def record(self, word: str, response_code: str | None) -> None:
        had: bool = word in self._codes
        if had and self._codes[word] == response_code:
            return
        old_category: int | None = (
            _state_category(self._codes[word]) if had else None
        )
        self._codes[word] = response_code
        rank: int = self._frequency_list.get_index(word) + 1
        if rank == 0:
            return  # Not ranked: never a candidate, nothing to retally.
        self._on_state_change(
            rank, old_category, _state_category(response_code)
        )

    @abstractmethod
    def _on_state_change(self, rank: int, old: int | None, new: int) -> None:
        """Update sufficient statistics after a word changed category.

        :param rank: the word's 1-based frequency rank
        :param old: previous `_state_category`, or None if the word had none
        :param new: new `_state_category`
        """

    def _nearest_candidate(self, target: int, exclude: set[str]) -> str | None:
        """Get the candidate word whose rank is nearest to the target.

        Searches outward from the target, so the cost is proportional to the
        distance to the nearest candidate. Ties prefer the more frequent word,
        matching the ascending scan of the stateless implementation.
        """
        words: list[str] = self._words
        n: int = self._n
        if n == 0:
            return None
        target = min(max(target, 1), n)
        for offset in range(max(target - 1, n - target) + 1):
            rank: int = target - offset
            if rank >= 1:
                word: str = words[rank - 1]
                if word not in self._codes and word not in exclude:
                    return word
            rank = target + offset
            if offset and rank <= n:
                word = words[rank - 1]
                if word not in self._codes and word not in exclude:
                    return word
        return None


class ThresholdSelector(_RankedSelector):
    """Working memory of the optimal-threshold strategy (OT).

    Keeps the tested (rank, label) pairs sorted; each draw re-sweeps the
    decision stump in O(tested) and picks the candidate nearest the boundary
    rank i*. This fixes the per-draw cost (formerly a full-list scan), but
    deliberately keeps the selection policy identical — including the known
    cold-start creep: while every tested word is known, i* sits at the
    highest tested rank and the probe advances rank by rank instead of the
    O(log V) search `metric.tex` claims (see the OT "Query selection"
    paragraph; a geometric/doubling probe is the pending fix).
    """

    def __init__(
        self, frequency_list: FrequencyList, states: WordStates
    ) -> None:
        super().__init__(frequency_list)
        self._tested: list[tuple[int, int]] = []
        self._ingest(states)

    @override
    def _on_state_change(self, rank: int, old: int | None, new: int) -> None:
        if old is not None and old != 2:
            self._tested.remove((rank, old))
        if new != 2:
            bisect.insort(self._tested, (rank, new))

    @override
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        # With no data yet, start at the most frequent candidate.
        target: int = _optimal_threshold(self._tested) if self._tested else 1
        return self._nearest_candidate(target, exclude)


class LogisticSelector(_RankedSelector):
    """Working memory of the logistic-adaptive strategy (LA).

    The model is refit at most once per recorded answer (warm-started from
    the previous parameters); candidate scoring is vectorized over cached
    per-rank arrays instead of a Python loop over the whole list.
    """

    def __init__(
        self, frequency_list: FrequencyList, states: WordStates
    ) -> None:
        super().__init__(frequency_list)
        self._squared_shares: np.ndarray = _squared_shares_by_rank(
            frequency_list
        )
        self._log_rank_values: np.ndarray = _log_ranks(frequency_list)
        self._candidate: np.ndarray = np.ones(self._n, dtype=bool)
        self._labels_by_rank: dict[int, int] = {}
        self._params: tuple[float, float, float] | None = None
        self._dirty: bool = True
        self._ingest(states)

    @override
    def _on_state_change(self, rank: int, old: int | None, new: int) -> None:
        self._candidate[rank - 1] = False
        if new != 2:
            self._labels_by_rank[rank] = new
        else:
            self._labels_by_rank.pop(rank, None)
        self._dirty = True

    def fit(self) -> tuple[float, float, float] | None:
        """Fit the logistic model if there is enough data, memoized.

        :return: (a, b, c), or None while the tested set is too small
        """
        labels: dict[int, int] = self._labels_by_rank
        if (
            sum(labels.values()) < MIN_N_UNKNOWN
            or len(labels) < MIN_SIZE_TESTED_RANKS
        ):
            self._params = None
        elif self._dirty:
            ranks: list[int] = sorted(labels)
            self._params = _fit_logistic(
                ranks, [labels[rank] for rank in ranks], initial=self._params
            )
        self._dirty = False
        return self._params

    @override
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        params: tuple[float, float, float] | None = self.fit()
        if params is None:
            return self._explore(exclude)
        a, b, c = params
        # Exploit: maximise p_i² · π_i (1 - π_i) over the candidates.
        pi: np.ndarray = c * expit(a * self._log_rank_values + b)
        scores: np.ndarray = np.where(
            self._candidate, self._squared_shares * pi * (1.0 - pi), -1.0
        )
        while True:
            index = int(np.argmax(scores))
            if scores[index] < 0.0:
                return None
            word: str = self._words[index]
            if word not in exclude:
                return word
            scores[index] = -1.0

    def _explore(self, exclude: set[str]) -> str | None:
        """Probe a log-uniform random rank until the model is fittable."""
        indices: np.ndarray = np.flatnonzero(self._candidate)
        max_rank: int = 0
        for index in indices[::-1]:
            if self._words[index] not in exclude:
                max_rank = int(index) + 1
                break
        if max_rank == 0:
            return None
        target: int = max(1, int(max_rank ** random.random()))
        return self._nearest_candidate(target, exclude)


class StratifiedSelector(_RankedSelector):
    """Working memory of the stratified strategy (SFWR).

    Divide the list into log-uniform strata, then query the stratum with the
    highest marginal variance reduction P_k² · θ̃_k (1 − θ̃_k) / (n_k (n_k +
    1)), where θ̃_k is the Laplace-smoothed unknown share among the stratum's
    n_k tested words. An untested stratum has infinite marginal value, so
    every stratum carrying mass is surveyed (unlocking the estimator, which
    requires full coverage) before any stratum is refined. Within the chosen
    stratum the word is drawn uniformly at random: θ̂_k weights tested words
    by frequency already, and a deterministic highest-frequency pick would
    sample each stratum from its most-known edge, biasing θ̂_k downward.

    Since a stratum is one contiguous rank range, the uniform draw is
    rejection sampling over ranks — no untested pools are materialized, which
    is what makes `record` O(1). The distribution is identical to drawing
    from an explicit pool of the stratum's untested words.
    """

    def __init__(
        self,
        frequency_list: FrequencyList,
        states: WordStates,
        n_strata: int = DEFAULT_N_STRATA,
    ) -> None:
        super().__init__(frequency_list)
        self._n_strata: int = n_strata
        self._bounds: list[tuple[int, int]] = _stratum_bounds(
            frequency_list, n_strata
        )
        self._p_total: list[float] = _stratum_masses(frequency_list, n_strata)
        self._shares: np.ndarray = _shares_by_rank(frequency_list)
        self._count: list[int] = [0] * n_strata
        self._count_unknown: list[int] = [0] * n_strata
        self._states_count: list[int] = [0] * n_strata
        self._p_tested: list[float] = [0.0] * n_strata
        self._p_unknown: list[float] = [0.0] * n_strata
        self._ingest(states)

    @override
    def _on_state_change(self, rank: int, old: int | None, new: int) -> None:
        k: int = stratum_of_rank(rank, self._n, self._n_strata)
        p_i: float = float(self._shares[rank - 1])
        if old is None:
            self._states_count[k] += 1
        elif old != 2:
            self._count[k] -= 1
            self._p_tested[k] -= p_i
            if old == 1:
                self._count_unknown[k] -= 1
                self._p_unknown[k] -= p_i
        if new != 2:
            self._count[k] += 1
            self._p_tested[k] += p_i
            if new == 1:
                self._count_unknown[k] += 1
                self._p_unknown[k] += p_i

    def _untested_count(self, k: int) -> int:
        lo, hi = self._bounds[k]
        return (hi - lo) - self._states_count[k]

    @override
    def next_word(self, exclude: set[str] | None = None) -> str | None:
        exclude = exclude or set()
        # A stratum may fail to yield a word when its every untested word is
        # excluded for this draw; fall through to the next-best stratum.
        failed: set[int] = set()
        while True:
            k: int | None = self._best_stratum(failed)
            if k is None:
                return None
            word: str | None = self._draw_from_stratum(k, exclude)
            if word is not None:
                return word
            failed.add(k)

    def _best_stratum(self, failed: set[int]) -> int | None:
        """Pick the stratum whose next query is most valuable.

        Coverage first: an untested stratum has infinite marginal value, the
        heaviest one winning; then greedy Neyman allocation by the marginal
        variance reduction score.
        """
        available: list[int] = [
            k
            for k in range(self._n_strata)
            if k not in failed and self._untested_count(k) > 0
        ]
        uncovered: list[int] = [k for k in available if self._count[k] == 0]
        if uncovered:
            return max(uncovered, key=lambda k: self._p_total[k])
        best_k: int | None = None
        best_score: float = -1.0
        for k in available:
            smoothed: float = (self._count_unknown[k] + 1) / (
                self._count[k] + 2
            )
            score: float = (
                self._p_total[k] ** 2
                * smoothed
                * (1.0 - smoothed)
                / (self._count[k] * (self._count[k] + 1))
            )
            if score > best_score:
                best_score = score
                best_k = k
        return best_k

    def _draw_from_stratum(self, k: int, exclude: set[str]) -> str | None:
        """Draw an untested stratum word uniformly, by rank rejection.

        Answered words are sparse in a large list, so a uniform rank usually
        hits an untested word within a few attempts; a nearly exhausted
        stratum falls back to one scan of its rank range.
        """
        lo, hi = self._bounds[k]
        words: list[str] = self._words
        codes: dict[str, str | None] = self._codes
        for _ in range(_SAMPLE_ATTEMPTS):
            word: str = words[random.randrange(lo, hi) - 1]
            if word not in codes and word not in exclude:
                return word
        pool: list[str] = [
            word
            for word in words[lo - 1 : hi - 1]
            if word not in codes and word not in exclude
        ]
        return random.choice(pool) if pool else None

    def theta_by_stratum(self) -> list[float]:
        """Get per-stratum frequency-weighted unknown shares θ̂_k.

        A stratum with no tested mass reports 0.5 (maximum uncertainty).
        """
        return [
            (
                self._p_unknown[k] / self._p_tested[k]
                if self._p_tested[k] > 0.0
                else 0.5
            )
            for k in range(self._n_strata)
        ]

    def estimate_theta(self) -> float:
        """Get the Horvitz—Thompson estimate θ̂ = Σ_k P_k · θ̂_k."""
        theta_k: list[float] = self.theta_by_stratum()
        return sum(self._p_total[k] * theta_k[k] for k in range(self._n_strata))


def create_selector(
    frequency_list: FrequencyList,
    selection: str,
    states: WordStates | None = None,
    answered: set[str] | None = None,
    n_strata: int = DEFAULT_N_STRATA,
) -> WordSelector:
    """Build the working memory of a selection strategy.

    :param frequency_list: source of candidate words
    :param selection: the lexicon's stored selection strategy
    :param states: per-word state, used by the model-based strategies
    :param answered: words already answered in the lexicon itself, used only
        by the `top` strategy (which never re-asks its own words but must
        still draw words answered in sibling lexicons, so their answers get
        propagated)
    :param n_strata: number of log-uniform strata for `stratified`
    :return: a selector seeded with the given states
    :raises NotImplementedError: for unknown strategies
    """
    match selection:
        case "frequency":
            return _SampledSelector(
                frequency_list, frequency_list.get_random_word_by_frequency
            )
        case "random":
            return _SampledSelector(
                frequency_list, frequency_list.get_random_word
            )
        case "top":
            return TopSelector(frequency_list, set(answered or ()))
        case "logistic":
            return LogisticSelector(frequency_list, states or {})
        case "threshold":
            return ThresholdSelector(frequency_list, states or {})
        case "stratified":
            return StratifiedSelector(frequency_list, states or {}, n_strata)
        case _:
            message = f"Selection `{selection}` is not supported over the API."
            raise NotImplementedError(message)


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
    ranks: list[int],
    labels: list[int],
    initial: tuple[float, float, float] | None = None,
) -> tuple[float, float, float]:
    """Fit 3-parameter logistic model π_i = c · σ(a · log(rank) + b).

    :param ranks: frequency ranks (1-indexed, 1 = most frequent)
    :param labels: 1 if unknown, 0 if known
    :param initial: previous fit to warm-start from, so an incremental refit
        after one more answer converges in a few iterations
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

    x0: np.ndarray = np.array([0.0, -5.0])  # t=0 → a=1
    if initial is not None:
        x0 = np.array([math.log(initial[0]), initial[1]])
    result = minimize(
        neg_log_likelihood,
        x0=x0,
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


TestedWord = tuple[int, float, int]
"""A tested word: (frequency rank, frequency share p_i, label, 1 = unknown)."""

UntestedWord = tuple[int, float]
"""An untested word: (frequency rank, frequency share p_i)."""

RateEstimator = Literal["frequency", "stratified", "threshold", "logistic"]
"""Identifier of a rate estimator.

It is named after the selection strategy whose logs it is designed for.
"""

RATE_ESTIMATOR_BY_SELECTION: dict[str, RateEstimator] = {
    "frequency": "frequency",
    "stratified": "stratified",
    "threshold": "threshold",
    "logistic": "logistic",
    # The logistic estimator does not require frequency-weighted draws: every
    # tested word enters θ̂ weighted by its true corpus frequency regardless
    # of how it was drawn. It therefore also serves the logs collected by the
    # non-frequency-weighted design strategies.
    "top": "logistic",
    "random": "logistic",
}
"""Which rate estimator each selection strategy's log must be fed to.

The design-based sliding window (`frequency`) is unbiased only over
frequency-weighted draws; a log collected under any other strategy needs the
estimator matching how the data was collected.
"""


def estimate_rate_frequency(
    sequence: list[int], precision: int = 100
) -> tuple[float, float] | None:
    """Estimate the rate from a frequency-weighted random sample (FWR).

    The point estimate is the last sliding window of `compute_lexicon_rate`:
    the stretch of the log ending at the latest "don't know" answer and
    containing exactly `precision` of them, giving r̂ = -log₂(n₋ / m). While
    the log has fewer than `precision` unknowns, the whole log is used
    instead, so an estimate appears early and tightens as answers accumulate.

    Each window is an inverse-binomial sample with n₋ failures, so
    SD(r̂) ≈ 1 / (ln 2 · √n₋), independent of the learner's level.

    :param sequence: chronological responses, 1 for "know", 0 for "don't"
    :param precision: number of "don't know" answers per full window
    :return: (r̂, SD), or None if there are not enough unknown answers
    """
    unknown_indices: list[int] = [
        index for index, response in enumerate(sequence) if response == 0
    ]
    number_of_unknowns: int = len(unknown_indices)
    if number_of_unknowns >= precision:
        start: int = (
            unknown_indices[-precision - 1] + 1
            if number_of_unknowns > precision
            else 0
        )
        window: int = unknown_indices[-1] - start + 1
        n_minus: int = precision
    elif number_of_unknowns >= MIN_N_UNKNOWN:
        window = len(sequence)
        n_minus = number_of_unknowns
    else:
        return None

    theta: float = n_minus / window
    return -math.log2(theta), 1.0 / (math.log(2) * math.sqrt(n_minus))


def estimate_rate_stratified(
    tested: list[TestedWord],
    untested: list[UntestedWord],
    resolved: list[UntestedWord] | None = None,
    n_strata: int = DEFAULT_N_STRATA,
) -> tuple[float, float] | None:
    """Estimate the rate from a stratified sample (SFWR).

    The Horvitz—Thompson estimator θ̂ = Σ_k P_k · θ̂_k over K log-uniform
    strata, where P_k is the stratum's total frequency mass and θ̂_k the
    frequency-weighted unknown share among its tested words (mirroring the
    interactive `check_stratified`). Every stratum carrying mass must have at
    least one tested word; SFWR's forced coverage reaches that after roughly
    one query per stratum.

    Var(θ̂) = Σ_k P_k² · θ̃_k (1 - θ̃_k) / n_k, with n_k the tested count in
    stratum k and θ̃_k the Laplace-smoothed unknown count share (so a stratum
    answered uniformly so far still contributes uncertainty), mapped to
    SD(r̂) = SD(θ̂) / (θ̂ ln 2) by the delta method.

    :param tested: tested words as (rank, frequency share, 1 = unknown)
    :param untested: untested words as (rank, frequency share)
    :param resolved: words resolved as unlearnable (not a word, proper noun):
        they count toward stratum mass but are never tested
    :param n_strata: number of log-uniform strata K
    :return: (r̂, SD), or None if some stratum has no tested words yet
    """
    resolved = resolved or []
    n: int = len(tested) + len(untested) + len(resolved)
    if n <= 1 or not tested:
        return None

    def stratum_of(rank: int) -> int:
        return stratum_of_rank(rank, n, n_strata)

    p_total: list[float] = [0.0] * n_strata
    p_tested: list[float] = [0.0] * n_strata
    p_unknown: list[float] = [0.0] * n_strata
    count: list[int] = [0] * n_strata
    count_unknown: list[int] = [0] * n_strata

    for rank, p_i, label in tested:
        k = stratum_of(rank)
        p_total[k] += p_i
        p_tested[k] += p_i
        count[k] += 1
        if label == 1:
            p_unknown[k] += p_i
            count_unknown[k] += 1
    for rank, p_i in untested:
        p_total[stratum_of(rank)] += p_i
    for rank, p_i in resolved:
        p_total[stratum_of(rank)] += p_i

    theta: float = 0.0
    variance: float = 0.0
    for k in range(n_strata):
        if p_total[k] <= 0.0:
            continue
        if count[k] == 0 or p_tested[k] <= 0.0:
            return None  # A rank decade carrying mass is still uncovered.
        theta += p_total[k] * p_unknown[k] / p_tested[k]
        smoothed: float = (count_unknown[k] + 1) / (count[k] + 2)
        variance += p_total[k] ** 2 * smoothed * (1.0 - smoothed) / count[k]

    if theta <= 0.0:
        return None
    return -math.log2(theta), math.sqrt(variance) / (theta * math.log(2))


def estimate_rate_threshold(
    tested: list[TestedWord],
    untested: list[UntestedWord],
    n_bootstrap: int = 200,
) -> tuple[float, float] | None:
    """Estimate the rate with the optimal frequency threshold (OT).

    θ̂ = Σ_{tested unknown} p_i + Σ_{untested, rank > i*} p_i, where i* is
    the misclassification-minimising boundary rank (see
    `_optimal_threshold`), and r̂ = -log₂(θ̂). The SD is bootstrapped:
    resampling the tested set moves the boundary, and only the untested tail
    term varies with it (the tested contribution is an exact observation, as
    in the logistic estimator).

    :param tested: tested words as (rank, frequency share, 1 = unknown)
    :param untested: untested words as (rank, frequency share)
    :param n_bootstrap: number of bootstrap resamples for the SD
    :return: (r̂, SD), or None if there is not enough data
    """
    n_unknown: int = sum(label for _, _, label in tested)
    if len(tested) < MIN_SIZE_TESTED_RANKS or n_unknown < MIN_N_UNKNOWN:
        return None

    theta_s: float = sum(p_i for _, p_i, label in tested if label == 1)

    # Suffix mass of untested words by rank, so the tail above any boundary
    # is one binary search away.
    by_rank: list[UntestedWord] = sorted(untested)
    ranks: list[int] = [rank for rank, _ in by_rank]
    suffix: list[float] = [0.0] * (len(by_rank) + 1)
    for index in range(len(by_rank) - 1, -1, -1):
        suffix[index] = suffix[index + 1] + by_rank[index][1]

    def tail(i_star: int) -> float:
        """Frequency mass of untested words with rank above the boundary."""
        return suffix[bisect.bisect_right(ranks, i_star)]

    paired: list[tuple[int, int]] = sorted(
        (rank, label) for rank, _, label in tested
    )
    theta: float = theta_s + tail(_optimal_threshold(paired))
    if theta <= 0.0:
        return None
    r_hat: float = -math.log2(theta)

    rng = np.random.default_rng()
    r_boots: list[float] = []
    for _ in range(n_bootstrap):
        indices = rng.integers(0, len(paired), size=len(paired))
        boot: list[tuple[int, int]] = sorted(paired[i] for i in indices)
        theta_boot: float = theta_s + tail(_optimal_threshold(boot))
        if theta_boot > 0.0:
            r_boots.append(-math.log2(theta_boot))

    if len(r_boots) < MIN_R_BOOTS:
        return None
    return r_hat, float(np.std(r_boots, ddof=1))


def estimate_rate_logistic(
    tested: list[TestedWord],
    untested: list[UntestedWord],
    n_bootstrap: int = 100,
) -> tuple[float, float] | None:
    """Estimate the rate with the logistic model (LA).

    θ̂ = Σ_{tested} p_i X_i + Σ_{untested} p_i · σ(a log rank + b) with
    (a, b) fitted by maximum likelihood, and r̂ = -log₂(θ̂). The SD is
    bootstrapped by refitting on resampled tested words; the tested
    contribution is an exact observation and is held fixed (as in
    `estimate_r_with_sd`). The untested sum is vectorised, so the bootstrap
    stays fast even over large frequency lists.

    :param tested: tested words as (rank, frequency share, 1 = unknown)
    :param untested: untested words as (rank, frequency share)
    :param n_bootstrap: number of bootstrap resamples for the SD
    :return: (r̂, SD), or None if there is not enough data
    """
    tested_ranks: list[int] = [rank for rank, _, _ in tested]
    tested_labels: list[int] = [label for _, _, label in tested]
    n_unknown: int = sum(tested_labels)
    if len(tested) < MIN_SIZE_TESTED_RANKS or n_unknown < MIN_N_UNKNOWN:
        return None

    theta_s: float = sum(p_i for _, p_i, label in tested if label == 1)

    log_ranks: np.ndarray = np.log([rank for rank, _ in untested])
    masses: np.ndarray = np.array([p_i for _, p_i in untested])

    def theta_u(a: float, b: float) -> float:
        """Model term: unknown mass predicted over the untested words."""
        return float(np.dot(masses, expit(a * log_ranks + b)))

    a, b, _ = _fit_logistic(tested_ranks, tested_labels)
    theta: float = theta_s + theta_u(a, b)
    if theta <= 0.0:
        return None
    r_hat: float = -math.log2(theta)

    ranks_arr: np.ndarray = np.array(tested_ranks)
    labels_arr: np.ndarray = np.array(tested_labels)
    n: int = len(tested)
    rng = np.random.default_rng()
    r_boots: list[float] = []
    for _ in range(n_bootstrap):
        indices = rng.integers(0, n, size=n)
        boot_labels: list[int] = cast("list[int]", labels_arr[indices].tolist())
        if 0 not in boot_labels or 1 not in boot_labels:
            continue
        boot_ranks: list[int] = cast("list[int]", ranks_arr[indices].tolist())
        try:
            a_b, b_b, _ = _fit_logistic(boot_ranks, boot_labels)
        except (ValueError, RuntimeError):
            continue
        theta_boot: float = theta_s + theta_u(a_b, b_b)
        if theta_boot > 0.0:
            r_boots.append(-math.log2(theta_boot))

    if len(r_boots) < MIN_R_BOOTS:
        return None
    return r_hat, float(np.std(r_boots, ddof=1))


def estimate_rate_with_sd(
    selection: str,
    frequency_list: FrequencyList | None = None,
    states: WordStates | None = None,
    sequence: list[int] | None = None,
    precision: int = 100,
) -> tuple[float, float] | None:
    """Estimate the rate with the estimator matching the selection strategy.

    Dispatches by `RATE_ESTIMATOR_BY_SELECTION`: a log is only meaningful to
    the estimator designed for the strategy it was collected under. The
    frequency estimator needs just the chronological answer sequence; the
    model-based estimators need the frequency list and the per-word states to
    place every word by rank.

    :param selection: the lexicon's stored selection strategy
    :param frequency_list: source of ranks and frequency shares, required by
        every estimator except the frequency one
    :param states: per-word latest state, as
        `postgres.get_language_word_states` returns
    :param sequence: chronological responses (1 "know" / 0 "don't"), required
        by the frequency estimator
    :param precision: number of "don't know" answers per frequency estimator
        window
    :return: (r̂, SD), or None if there is not enough data
    :raises NotImplementedError: for strategies without a rate estimator
    """
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(selection)
    if method is None:
        message = f"No rate estimator for selection `{selection}`."
        raise NotImplementedError(message)

    if method == "frequency":
        return estimate_rate_frequency(sequence or [], precision)

    if frequency_list is None:
        message = "Model-based rate estimators need a frequency list."
        raise ValueError(message)

    know: str = LexiconResponse.KNOW.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    total: int = frequency_list.get_all_occurrences()
    tested: list[TestedWord] = []
    untested: list[UntestedWord] = []
    resolved: list[UntestedWord] = []
    for rank, word in enumerate(frequency_list.get_words(), start=1):
        p_i: float = frequency_list.get_occurrences(word) / total
        state: tuple[str | None, bool | None] | None = (states or {}).get(word)
        if state is None:
            untested.append((rank, p_i))
        elif state[0] == know:
            tested.append((rank, p_i, 0))
        elif state[0] == dont:
            tested.append((rank, p_i, 1))
        else:
            # Resolved as not learnable (e.g. not a word, proper noun):
            # neither tested nor a candidate, but its frequency mass still
            # counts toward stratum totals.
            resolved.append((rank, p_i))

    if method == "stratified":
        return estimate_rate_stratified(tested, untested, resolved)
    if method == "threshold":
        return estimate_rate_threshold(tested, untested)
    return estimate_rate_logistic(tested, untested)


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

        # `file_path` is vestigial (records live in the database); kept only to
        # satisfy the `UserArtifact` base. Synthesized from the identifier.
        file_path: Path = path / f"{id_}.json"

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

    def get_word_states(self) -> WordStates:
        """Get every word's latest state, as a selector expects it.

        The in-memory equivalent of `postgres.get_language_word_states`,
        scoped to this lexicon.
        """
        return {
            word: (knowledge.knowing.to_code(), knowledge.to_skip)
            for word, knowledge in self.words.items()
        }

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

    async def check(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at_wrong: int | None,
    ) -> None:
        """Check lexicon."""
        selection: LexiconSelection = self.lexicon.config.selection
        if selection == LexiconSelection.FREQUENCY:
            await self.check_frequency(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )
        elif selection == LexiconSelection.RANDOM:
            await self.check_random(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )
        elif selection == LexiconSelection.TOP:
            await self.check_top(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )
        elif selection == LexiconSelection.LOGISTIC:
            await self.check_logistic(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )
        elif selection == LexiconSelection.STRATIFIED:
            await self.check_stratified(
                other_lexicons,
                frequency_list,
                stop_at=None,
                stop_at_wrong=stop_at_wrong,
            )

    def _record_state(
        self, record: Callable[[str, str | None], None] | None, word: str
    ) -> None:
        """Feed a word's new lexicon state back into a selector, if any."""
        if record is not None and self.lexicon.has(word):
            record(word, self.lexicon.get(word).to_code())

    async def _check_loop(
        self,
        other_lexicons: list["Lexicon"],
        pick_next: Callable[[], Awaitable[str | None]],
        stop_at: int | None,
        stop_at_wrong: int | None,
        record: Callable[[str, str | None], None] | None = None,
    ) -> str:
        """Run the interactive checking loop with a pluggable word picker.

        This is the shared body of every strategy. Each strategy supplies a
        ``pick_next`` coroutine that returns the next word to ask, or ``None``
        when its candidates are exhausted; the model-based strategies also
        supply ``record`` (their selector's), so every answer — asked or
        propagated by `do_skip` — updates the selector's working memory.

        :param other_lexicons: other user lexicons of the same language
        :param pick_next: coroutine yielding the next word, or ``None`` to stop
        :param stop_at: stop after a number of actions
        :param stop_at_wrong: stop after a number of unknown words
        :param record: selector feedback for every word that gained a state
        :return: exit code
        """
        session: LexiconLogSession = LexiconLogSession(start=datetime.now(UTC))

        actions: int = 0
        wrong_answers: int = 0
        exit_code: str = "quit"

        while True:
            picked_word: str | None = await pick_next()
            if picked_word is None:
                break

            if self.do_skip(picked_word, other_lexicons):
                self._record_state(record, picked_word)
                continue

            _, response, _ = await self.ask(picked_word)
            self._record_state(record, picked_word)
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

    async def check_frequency(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
    ) -> str:
        """Check vocabulary using frequency-weighted random sampling (FWR).

        Words are drawn with probability proportional to their corpus
        frequency.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: list of the words with frequency to check
        :param stop_at: stop after a number of actions
        :param stop_at_wrong: stop after a number of unknown words
        :return: exit code
        """
        # If all words are checked, stop. This may happen only if the frequency
        # list is too small.
        checked_in_session: set[str] = set()

        async def pick_next() -> str | None:
            if len(checked_in_session) >= len(frequency_list):
                return None
            picked_word, _ = frequency_list.get_random_word_by_frequency()
            if picked_word:
                checked_in_session.add(picked_word)
            return picked_word

        return await self._check_loop(
            other_lexicons, pick_next, stop_at, stop_at_wrong
        )

    async def check_random(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
    ) -> str:
        """Check vocabulary by sampling words uniformly at random.

        Unlike FWR, each unique word form is equally likely, regardless of its
        corpus frequency.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: list of the words with frequency to check
        :param stop_at: stop after a number of actions
        :param stop_at_wrong: stop after a number of unknown words
        :return: exit code
        """
        checked_in_session: set[str] = set()

        async def pick_next() -> str | None:
            if len(checked_in_session) >= len(frequency_list):
                return None
            picked_word, _ = frequency_list.get_random_word()
            if picked_word:
                checked_in_session.add(picked_word)
            return picked_word

        return await self._check_loop(
            other_lexicons, pick_next, stop_at, stop_at_wrong
        )

    async def check_top(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
    ) -> str:
        """Check vocabulary by walking the frequency list in rank order.

        Picks the most frequent not-yet-answered word, skipping words that are
        not common according to the dictionaries.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: list of the words with frequency to check
        :param stop_at: stop after a number of actions
        :param stop_at_wrong: stop after a number of unknown words
        :return: exit code
        """
        index: int = 0

        async def pick_next() -> str | None:
            nonlocal index
            while index < len(frequency_list):
                picked_word, _ = frequency_list.get_word_by_index(index)
                index += 1
                if self.lexicon.has(picked_word):
                    continue
                items: list[DictionaryItem] = await self.dictionaries.get_items(
                    picked_word, self.lexicon.language
                )
                if not items or items[0].is_not_common(self.lexicon.language):
                    continue
                return picked_word
            return None

        return await self._check_loop(
            other_lexicons, pick_next, stop_at, stop_at_wrong
        )

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
        Falls back to log-uniform exploration until enough data exists to fit
        the model. The selection lives in `LogisticSelector`; this loop only
        adds interactive logging around it.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: frequency list to use for word selection
        :param stop_at: stop after this many user interactions
        :param stop_at_wrong: stop after this many unknown words found
        :return: exit code
        """
        selector: LogisticSelector = LogisticSelector(
            frequency_list, self.lexicon.get_word_states()
        )

        async def pick_next() -> str | None:
            if params := selector.fit():
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
            return selector.next_word()

        return await self._check_loop(
            other_lexicons,
            pick_next,
            stop_at,
            stop_at_wrong,
            record=selector.record,
        )

    async def check_stratified(
        self,
        other_lexicons: list["Lexicon"],
        frequency_list: FrequencyList,
        stop_at: int | None,
        stop_at_wrong: int | None,
        n_strata: int = DEFAULT_N_STRATA,
    ) -> str:
        """Check vocabulary using stratified frequency-weighted random sampling.

        Implements SFWR; the allocation rule and the draw live in
        `StratifiedSelector`, this loop only adds interactive logging around
        it. The combined estimator is the Horvitz-Thompson estimate
        theta = sum_k P_k * theta_k, with theta_k the frequency-weighted
        unknown share among tested words.

        :param other_lexicons: other user lexicons of the same language
        :param frequency_list: frequency list used for word selection
        :param stop_at: stop after this many user interactions
        :param stop_at_wrong: stop after this many unknown words found
        :param n_strata: number of log-uniform strata K
        :return: exit code
        """
        selector: StratifiedSelector = StratifiedSelector(
            frequency_list, self.lexicon.get_word_states(), n_strata
        )

        async def pick_next() -> str | None:
            theta: float = selector.estimate_theta()
            if theta > 0.0:
                logger.info(
                    "r = %.2f | theta_k: %s",
                    -math.log2(theta),
                    " ".join(
                        f"{value:.2f}" for value in selector.theta_by_stratum()
                    ),
                )
            return selector.next_word()

        return await self._check_loop(
            other_lexicons,
            pick_next,
            stop_at,
            stop_at_wrong,
            record=selector.record,
        )

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
