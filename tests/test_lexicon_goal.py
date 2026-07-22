"""Tests for the fixed lexicon precision goal (`emmio.lexicon.goal`)."""

from datetime import UTC, datetime, timedelta

from emmio.lexicon.config import LexiconSelection
from emmio.lexicon.goal import (
    RECHECK_DELAY_DAYS,
    SD_THRESHOLD,
    WINDOW_DAYS,
    LexiconGoalState,
    _windowed_sequence_and_states,
    compute_lexicon_goal_state,
)


def dt(year: int, month: int, day: int) -> datetime:
    """Create a UTC-aware datetime for tests."""
    return datetime(year, month, day, tzinfo=UTC)


def test_windowed_sequence_and_states_drops_stale_answers() -> None:
    """A know/don't-know answer older than the cutoff reverts to untested.

    A resolution (not a word) stays valid regardless of age, and a later
    answer inside the window overrides a stale one for the same word.
    """
    now: datetime = dt(2024, 4, 1)
    cutoff: datetime = now - timedelta(days=WINDOW_DAYS)

    records: list[tuple[datetime, str, str]] = [
        (cutoff - timedelta(days=1), "old_dont", "D"),
        (cutoff + timedelta(days=1), "recent_know", "K"),
        (cutoff - timedelta(days=30), "resolved_old", "N"),
        (cutoff - timedelta(days=1), "overridden", "D"),
        (cutoff + timedelta(days=2), "overridden", "K"),
    ]

    sequence, states = _windowed_sequence_and_states(records, cutoff)

    # The stale "don't know" is gone; the resolution never expires; the
    # overridden word keeps only its latest (in-window) answer.
    assert states == {
        "recent_know": ("K", None),
        "resolved_old": ("N", None),
        "overridden": ("K", None),
    }
    # The sequence counts every in-window know/don't-know row, not just the
    # latest per word (each row is one query event, like the plain answer
    # sequence elsewhere in the codebase).
    assert sequence == [1, 1]


def test_compute_lexicon_goal_state_frequency_windows_by_date() -> None:
    """FWR: only "don't know" answers within the trailing window count."""
    now: datetime = dt(2024, 4, 1)

    # 120 recent "don't know" answers, comfortably over the 100 the default
    # precision needs, plus 50 old ones that must not count.
    recent: list[tuple[datetime, str, str]] = [
        (now - timedelta(minutes=i), f"recent{i}", "D") for i in range(120)
    ]
    old: list[tuple[datetime, str, str]] = [
        (now - timedelta(days=100, minutes=i), f"old{i}", "D")
        for i in range(50)
    ]

    state: LexiconGoalState = compute_lexicon_goal_state(
        LexiconSelection.FREQUENCY, None, recent + old, now
    )
    assert state.has_estimator
    assert state.achieved
    assert state.sd is not None
    assert state.sd <= SD_THRESHOLD
    assert state.recheck_available_at == recent[0][0] + timedelta(
        days=RECHECK_DELAY_DAYS
    )

    # With only the old (out-of-window) answers, there is nothing recent
    # enough to trust: not achieved, no recheck timer.
    state_stale: LexiconGoalState = compute_lexicon_goal_state(
        LexiconSelection.FREQUENCY, None, old, now
    )
    assert not state_stale.achieved
    assert state_stale.recheck_available_at is None
    assert state_stale.check_available


def test_compute_lexicon_goal_state_has_no_estimator_for_arbitrary() -> None:
    """An `arbitrary` lexicon has no check method, so no goal to track."""
    state: LexiconGoalState = compute_lexicon_goal_state(
        LexiconSelection.ARBITRARY, None, [], dt(2024, 4, 1)
    )
    assert not state.has_estimator
    assert not state.achieved
    assert state.check_available
