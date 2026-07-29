"""Windowed rate history: the vocabulary rate as it changes through time.

Every selection strategy gets its history the same way: a sliding window over
the chronological answer log, kept as small as the strategy-matched estimator
allows while its standard deviation stays under a threshold. A small window
follows the learner's progress closely; the threshold keeps every point equally
trustworthy across strategies, so their curves are comparable on one graph.

The frequency (FWR) backend reuses `compute_lexicon_rate`: its windows of a
fixed number of "don't know" answers are exactly the SD-threshold windows for
that estimator, whose SD = 1 / (ln 2 · √n₋) depends on the unknown count alone.
The classic 100-don't-know research method is the special case `sd_threshold =
DEFAULT_SD_THRESHOLD`.

The stratified (SFWR) backend maintains the estimator's per-stratum aggregates
incrementally and moves the window with two pointers: each answer enters the
window once and leaves at most once, and every check against the threshold is an
O(K) evaluation of `_stratified_rate_from_aggregates`, so a whole history costs
O(N · K) — nothing is ever recomputed from scratch.

The threshold and logistic estimators have no windowed history yet: their
bootstrapped SDs admit no O(1) update, so they need a warm-started window search
instead of two pointers.
"""

import math
from datetime import datetime

from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    RATE_ESTIMATOR_BY_SELECTION,
    LexiconResponse,
    RateEstimator,
    _shares_by_rank,
    _stratified_rate_from_aggregates,
    _stratum_bounds,
    _stratum_masses,
    compute_lexicon_rate,
    stratum_of_rank,
)
from emmio.lists.frequency_list import FrequencyList

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DEFAULT_SD_THRESHOLD: float = 1.0 / (math.log(2) * math.sqrt(100))
"""Target standard deviation of every history point, ≈ 0.144.

Chosen to preserve the classic FWR history: a full window of 100 "don't
know" answers has SD = 1 / (ln 2 · √100), so under this threshold the
frequency backend reproduces the traditional 100-don't-know windows exactly.
"""

RateHistory = tuple[
    list[int], list[tuple[datetime, datetime]], list[float], list[float]
]
"""A rate history.

1-based record positions, window (start, end) dates, rates and SDs,
index-aligned.
"""


def compute_rate_history(
    selection: LexiconSelection,
    frequency_list: FrequencyList | None,
    records: list[tuple[datetime, str, str]],
    sd_threshold: float = DEFAULT_SD_THRESHOLD,
    n_strata: int = DEFAULT_N_STRATA,
) -> RateHistory:
    """Compute the windowed rate history of a lexicon's answer log.

    Dispatches to the estimator matching the selection strategy, like
    `estimate_rate_with_sd`; every emitted point is the estimate over the
    smallest stretch of the log ending at that answer whose SD is under
    `sd_threshold`, so no point appears until the log first supports the
    required precision.

    :param selection: the lexicon's stored selection strategy
    :param frequency_list: source of ranks and frequency shares, required by
        every estimator except the frequency one
    :param records: chronological (response time, word, response code) log,
        including resolutions, as `postgres.get_lexicon_dated_record_log`
        returns
    :param sd_threshold: largest standard deviation a history point may have
    :param n_strata: number of log-uniform strata K for the stratified
        estimator
    :return: 1-based positions in `records`, window date ranges, rates and
        their SDs, index-aligned
    :raises NotImplementedError: for estimators without a windowed history
    :raises ValueError: if a model-based estimator gets no frequency list
    """
    method: RateEstimator | None = RATE_ESTIMATOR_BY_SELECTION.get(selection)
    if method == RateEstimator.FREQUENCY:
        return _frequency_history(records, sd_threshold)
    if method == RateEstimator.STRATIFIED:
        if frequency_list is None:
            message = "The stratified rate history needs a frequency list."
            raise ValueError(message)
        return _stratified_history(
            frequency_list, records, sd_threshold, n_strata
        )
    message = f"No windowed rate history for selection `{selection}`."
    raise NotImplementedError(message)


def latest_windowed_rate(
    selection: LexiconSelection,
    frequency_list: FrequencyList | None,
    records: list[tuple[datetime, str, str]],
    sd_threshold: float = DEFAULT_SD_THRESHOLD,
    n_strata: int = DEFAULT_N_STRATA,
) -> tuple[float, float] | None:
    """Get the last point of `compute_rate_history`, the live counterpart.

    `None` while the log has never yet supported the target precision, same
    as `compute_rate_history` before its first emitted point.

    :raises NotImplementedError: for estimators without a windowed history
    :raises ValueError: if a model-based estimator gets no frequency list
    """
    _, _, rates, sds = compute_rate_history(
        selection, frequency_list, records, sd_threshold, n_strata
    )
    if not rates:
        return None
    return rates[-1], sds[-1]


def _frequency_history(
    records: list[tuple[datetime, str, str]], sd_threshold: float
) -> RateHistory:
    """Compute the windowed history of a frequency-weighted (FWR) log.

    SD(r̂) = 1 / (ln 2 · √n₋) depends only on the window's "don't know"
    count, so the smallest window under the threshold is the one with the
    smallest sufficient n₋ — exactly the fixed-unknown-count windows of
    `compute_lexicon_rate`. Positions are recovered by re-deriving the same
    "don't know" indices `compute_lexicon_rate` uses internally and mapping
    them back through `data`'s own positions in the full, unfiltered `records`.
    """
    precision: int = math.ceil((1.0 / (sd_threshold * math.log(2))) ** 2 - 1e-9)
    know: str = LexiconResponse.KNOW.to_code()
    know_class: str = LexiconResponse.KNOW_SEMANTIC_CLASS.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    data: list[tuple[datetime, int]] = []
    positions: list[int] = []  # 1-based position in `records` per `data` entry
    for position, (date, _, code) in enumerate(records, start=1):
        if code in (know, know_class, dont):
            data.append((date, 0 if code == dont else 1))
            positions.append(position)

    unknown_indices: list[int] = [
        index for index, (_, response) in enumerate(data) if response == 0
    ]
    if len(unknown_indices) < precision:
        return [], [], [], []

    date_ranges, rates = compute_lexicon_rate(data, precision)
    queries: list[int] = [
        positions[unknown_indices[index + precision - 1]]
        for index in range(len(rates))
    ]
    sd: float = 1.0 / (math.log(2) * math.sqrt(precision))
    return queries, date_ranges, rates, [sd] * len(rates)


def _stratified_history(
    frequency_list: FrequencyList,
    records: list[tuple[datetime, str, str]],
    sd_threshold: float,
    n_strata: int = DEFAULT_N_STRATA,
) -> RateHistory:
    """Compute the windowed history of a stratified (SFWR) log.

    Two pointers over the log with incremental per-stratum aggregates. Only
    the latest answer for a word counts inside a window (n_k feeds the finite
    population correction, so a word must not be counted twice); an answer
    superseded by a re-ask goes inactive immediately and is skipped when the
    left pointer reaches it. Resolutions (not a word, proper noun) are facts
    about the list rather than knowledge at a moment, so they accumulate and
    never expire with the window.
    """
    know: str = LexiconResponse.KNOW.to_code()
    know_class: str = LexiconResponse.KNOW_SEMANTIC_CLASS.to_code()
    dont: str = LexiconResponse.DONT.to_code()
    shares = _shares_by_rank(frequency_list)
    size: int = len(frequency_list)
    bounds: list[tuple[int, int]] = _stratum_bounds(frequency_list, n_strata)
    p_total: list[float] = _stratum_masses(frequency_list, n_strata)

    count: list[int] = [0] * n_strata
    count_unknown: list[int] = [0] * n_strata
    p_tested: list[float] = [0.0] * n_strata
    p_unknown: list[float] = [0.0] * n_strata
    n_resolved: list[int] = [0] * n_strata

    # The window is the contributing part of `entries[left:]`: an entry as
    # (date, word, stratum, frequency share, 1 = unknown).
    entries: list[tuple[datetime, str, int, float, int]] = []
    contributing: list[bool] = []
    active: dict[str, int] = {}
    """Word → index of its contributing entry, for every word in the window."""
    resolved_words: set[str] = set()
    left: int = 0

    queries: list[int] = []
    date_ranges: list[tuple[datetime, datetime]] = []
    rates: list[float] = []
    sds: list[float] = []

    def evaluate() -> tuple[float, float] | None:
        return _stratified_rate_from_aggregates(
            p_total,
            p_tested,
            p_unknown,
            count,
            count_unknown,
            bounds,
            n_resolved,
        )

    def add(k: int, p_i: float, label: int) -> None:
        count[k] += 1
        p_tested[k] += p_i
        if label == 1:
            count_unknown[k] += 1
            p_unknown[k] += p_i

    def remove(k: int, p_i: float, label: int) -> None:
        count[k] -= 1
        p_tested[k] -= p_i
        if label == 1:
            count_unknown[k] -= 1
            p_unknown[k] -= p_i

    def deactivate(index: int) -> None:
        _, word, k, p_i, label = entries[index]
        contributing[index] = False
        del active[word]
        remove(k, p_i, label)

    for position, (date, word, code) in enumerate(records, start=1):
        index: int = frequency_list.get_index(word)
        if index == -1:
            continue  # A word outside the list is invisible to the estimator.
        k: int = stratum_of_rank(index + 1, size, n_strata)
        p_i: float = float(shares[index])

        if code not in (know, know_class, dont):
            if word in active:
                deactivate(active[word])
            if word not in resolved_words:
                resolved_words.add(word)
                n_resolved[k] += 1
            continue

        label: int = 1 if code == dont else 0
        if word in resolved_words:
            # A later answer overrides a stale resolution.
            resolved_words.discard(word)
            n_resolved[k] -= 1
        if word in active:
            deactivate(active[word])
        entries.append((date, word, k, p_i, label))
        contributing.append(True)
        active[word] = len(entries) - 1
        add(k, p_i, label)

        estimate: tuple[float, float] | None = evaluate()
        if estimate is None or estimate[1] > sd_threshold:
            continue  # The whole retained log is still too noisy.

        # Shrink to the smallest suffix still under the threshold. SD is not
        # strictly monotone in window size (the smoothed θ̃_k shifts as
        # answers drop out), but the check is direct — no monotonicity is
        # assumed — so at worst the window stays slightly larger than the
        # true minimum.
        while left < len(entries) - 1:
            if not contributing[left]:
                left += 1
                continue
            _, _, k_left, p_left, label_left = entries[left]
            remove(k_left, p_left, label_left)
            candidate: tuple[float, float] | None = evaluate()
            if candidate is None or candidate[1] > sd_threshold:
                add(k_left, p_left, label_left)
                break
            estimate = candidate
            contributing[left] = False
            del active[entries[left][1]]
            left += 1

        queries.append(position)
        date_ranges.append((entries[left][0], date))
        rates.append(estimate[0])
        sds.append(estimate[1])

    return queries, date_ranges, rates, sds
