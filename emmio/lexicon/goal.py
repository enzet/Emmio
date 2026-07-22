"""Fixed goal parameters for lexicon precision tracking.

A lexicon's rate estimate is considered *trustworthy* once its standard
deviation, computed with the estimator matching the lexicon's selection
strategy over only the trailing `WINDOW_DAYS` of answers, is at or under
`SD_THRESHOLD`. Once trustworthy, rechecking is paused for
`RECHECK_DELAY_DAYS`, so an estimate that is already good enough is not
re-tested more than about once a week.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.core import (
    RATE_ESTIMATOR_BY_SELECTION,
    LexiconResponse,
    WordStates,
    estimate_rate_with_sd,
)
from emmio.lexicon.history import DEFAULT_SD_THRESHOLD
from emmio.lists.frequency_list import FrequencyList

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

SD_THRESHOLD: float = DEFAULT_SD_THRESHOLD
"""Target standard deviation of the rate estimate."""

WINDOW_DAYS: int = 90
"""Trailing window the precision target must hold over."""

RECHECK_DELAY_DAYS: int = 7
"""Minimum number of days between reaching the target and rechecking."""


@dataclass(frozen=True)
class LexiconGoalState:
    """Whether a lexicon currently meets its precision target."""

    has_estimator: bool
    """Whether the selection strategy has a rate estimator at all.

    `False` for `arbitrary`/`unknown` lexicons, which have no check method;
    such a lexicon has no goal to track, so it is always available to check.
    """

    achieved: bool
    """Whether the trailing-window estimate's SD is at or under the target."""

    rate: float | None
    """The trailing-window rate estimate, or `None` if not enough data."""

    sd: float | None
    """The trailing-window estimate's standard deviation."""

    recheck_available_at: datetime | None
    """When the "Check" button unlocks again, or `None` if available now."""

    @property
    def check_available(self) -> bool:
        """Whether checking is allowed right now."""
        if not self.achieved:
            return True
        return (
            self.recheck_available_at is None
            or datetime.now(UTC) >= self.recheck_available_at
        )


def _windowed_sequence_and_states(
    records: list[tuple[datetime, str, str]], cutoff: datetime
) -> tuple[list[int], WordStates]:
    """Build a windowed sequence/state view of a chronological answer log.

    A know/don't-know answer older than `cutoff` reverts its word to
    untested, since its knowledge is no longer trusted to be current; a
    resolution (not a word, proper noun) stays valid regardless of age, since
    it is a fact about the list rather than knowledge that can go stale.

    :param records: chronological (response time, word, response code) log,
        as `postgres.get_lexicon_dated_record_log` returns
    :param cutoff: the window's start; only know/don't-know answers at or
        after this instant count as tested
    :return: (windowed chronological 1/0 sequence, windowed word states)
    """
    know: str = LexiconResponse.KNOW.to_code()
    dont: str = LexiconResponse.DONT.to_code()

    latest: dict[str, tuple[datetime, str]] = {}
    for date, word, code in records:
        latest[word] = (date, code)

    sequence: list[int] = [
        1 if code == know else 0
        for date, _, code in records
        if code in (know, dont) and date >= cutoff
    ]
    states: WordStates = {}
    for word, (date, code) in latest.items():
        if code in (know, dont):
            if date >= cutoff:
                states[word] = (code, None)
        else:
            states[word] = (code, None)
    return sequence, states


def compute_lexicon_goal_state(
    selection: LexiconSelection,
    frequency_list: FrequencyList | None,
    records: list[tuple[datetime, str, str]],
    now: datetime | None = None,
) -> LexiconGoalState:
    """Compute whether a lexicon currently meets its precision target.

    Dispatches to the estimator matching `selection` (as `estimate_rate_with_sd`
    does), restricted to the trailing `WINDOW_DAYS`: a know/don't-know answer
    older than that no longer counts as tested, so the estimate reflects only
    knowledge that is still fresh.

    :param selection: the lexicon's stored selection strategy
    :param frequency_list: source of ranks and frequency shares, required by
        every estimator except the frequency one
    :param records: chronological (response time, word, response code) log,
        as `postgres.get_lexicon_dated_record_log` returns
    :param now: evaluation instant, defaults to the current time
    :return: the lexicon's current goal state
    """
    if RATE_ESTIMATOR_BY_SELECTION.get(selection) is None:
        return LexiconGoalState(
            has_estimator=False,
            achieved=False,
            rate=None,
            sd=None,
            recheck_available_at=None,
        )

    now = now or datetime.now(UTC)
    cutoff: datetime = now - timedelta(days=WINDOW_DAYS)
    sequence, states = _windowed_sequence_and_states(records, cutoff)

    try:
        estimate: tuple[float, float] | None = estimate_rate_with_sd(
            selection, frequency_list, states, sequence
        )
    except ValueError:
        # A model-based estimator with no frequency list to place words by
        # rank: nothing to compute, same as not enough data yet.
        estimate = None
    rate, sd = estimate if estimate is not None else (None, None)
    achieved: bool = sd is not None and sd <= SD_THRESHOLD

    recheck_available_at: datetime | None = None
    if achieved:
        last_time: datetime | None = max(
            (date for date, _, _ in records if date >= cutoff), default=None
        )
        if last_time is not None:
            recheck_available_at = last_time + timedelta(
                days=RECHECK_DELAY_DAYS
            )

    return LexiconGoalState(
        has_estimator=True,
        achieved=achieved,
        rate=rate,
        sd=sd,
        recheck_available_at=recheck_available_at,
    )
