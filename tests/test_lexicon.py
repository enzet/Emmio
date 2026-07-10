"""Tests for lexicon."""

import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    Lexicon,
    LexiconLog,
    LexiconResponse,
    estimate_rate_frequency,
    estimate_rate_logistic,
    estimate_rate_stratified,
    estimate_rate_threshold,
    estimate_rate_with_sd,
    select_next_word,
    stratum_of_rank,
)
from emmio.lists.config import (
    FrequencyListConfig,
    FrequencyListFileFormat,
    ListUsageConfig,
)
from emmio.lists.frequency_list import FrequencyList
from emmio.ui import TerminalInterface


def dt(year: int, month: int, day: int) -> datetime:
    """Create a UTC-aware datetime for tests."""
    return datetime(year, month, day, tzinfo=UTC)


def _frequency_list(data: dict[str, int]) -> FrequencyList:
    """Build an in-memory frequency list for tests."""
    return FrequencyList(
        file_path=Path("unused"),
        config=FrequencyListConfig(
            file_format=FrequencyListFileFormat.LIST,
            language="en",
            path="unused",
            is_stripped=False,
        ),
        data=data,
    )


def test_select_next_word_skips_answered_words() -> None:
    """Selected words are drawn from the list and never already answered."""

    frequency_list: FrequencyList = _frequency_list(
        {"the": 100, "cat": 50, "dog": 10}
    )
    words: set[str] = {"the", "cat", "dog"}

    for selection in ("frequency", "random"):
        word = select_next_word(frequency_list, {"the", "cat"}, selection)
        assert word == "dog"  # Only unanswered word.
        assert select_next_word(frequency_list, words, selection) is None
        assert select_next_word(frequency_list, set(), selection) in words


def test_select_next_word_rejects_unsupported_strategy() -> None:
    """Strategies not served over the API raise."""

    frequency_list: FrequencyList = _frequency_list({"the": 100})

    with pytest.raises(NotImplementedError):
        select_next_word(frequency_list, set(), "binary_search")


def _ranked_frequency_list(size: int) -> FrequencyList:
    """Build a frequency list of `size` words with strictly decreasing counts.

    Word `w{i}` has rank `i + 1` (most frequent first), so rank and knowledge
    can be reasoned about directly in tests.
    """
    return _frequency_list({f"w{i}": size - i for i in range(size)})


def test_stratum_of_rank_covers_and_orders_strata() -> None:
    """Ranks map to valid, monotonic strata; the extremes hit both ends."""

    size: int = 10_000
    strata: list[int] = [
        stratum_of_rank(rank, size) for rank in range(1, size + 1)
    ]
    assert strata[0] == 0
    assert strata[-1] == DEFAULT_N_STRATA - 1
    assert all(0 <= k < DEFAULT_N_STRATA for k in strata)
    assert strata == sorted(strata)  # Higher rank never lowers the stratum.
    # A single-word list degenerates to the first stratum.
    assert stratum_of_rank(1, 1) == 0


def test_select_next_word_top_walks_by_rank() -> None:
    """`top` returns the most frequent word not already excluded."""

    frequency_list: FrequencyList = _ranked_frequency_list(5)

    assert select_next_word(frequency_list, set(), "top") == "w0"
    assert select_next_word(frequency_list, {"w0", "w1"}, "top") == "w2"


def test_select_next_word_threshold_targets_the_boundary() -> None:
    """`threshold` picks an untested word near the known/unknown boundary."""

    frequency_list: FrequencyList = _ranked_frequency_list(20)
    # Words below rank ~10 are known, above are unknown; w9/w10 are untested.
    states: dict[str, tuple[str | None, bool | None]] = {}
    for i in range(20):
        if i in (9, 10):
            continue
        states[f"w{i}"] = (("K" if i < 10 else "D"), None)

    word = select_next_word(frequency_list, set(), "threshold", states)
    assert word in {"w9", "w10"}


def test_select_next_word_model_strategies_skip_answered() -> None:
    """Model strategies never re-pick a word that already has a response."""

    frequency_list: FrequencyList = _ranked_frequency_list(6)
    states: dict[str, tuple[str | None, bool | None]] = {
        f"w{i}": (("K" if i % 2 else "D"), None) for i in range(5)
    }  # Only `w5` is untested.

    for strategy in ("logistic", "threshold", "stratified"):
        assert select_next_word(frequency_list, set(), strategy, states) == "w5"


@pytest.fixture(name="lexicon")
def fixture_lexicon() -> Lexicon:
    """Test lexicon checking process."""

    with tempfile.TemporaryDirectory() as temp_directory:
        lexicon_instance: Lexicon = Lexicon.from_config(
            Path(temp_directory),
            "en",
            LexiconConfig(
                language="en",
                frequency_list=ListUsageConfig(id="en"),
                selection=LexiconSelection.ARBITRARY,
            ),
            "test",
        )
        lexicon_instance.log = LexiconLog()
        return lexicon_instance


def test_register(lexicon: Lexicon) -> None:
    """Test registering a word in the lexicon."""

    lexicon.register(
        word="apple",
        interface=TerminalInterface(use_input=False),
        response=LexiconResponse.KNOW,
        to_skip=False,
        time=dt(2000, 1, 1),
        request_time=dt(2000, 1, 1),
    )
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW


def register(lexicon: Lexicon, args: list[int]) -> None:
    """Register a word in the lexicon."""

    for index, arg in enumerate(args):
        lexicon.register(
            word="apple",
            interface=TerminalInterface(use_input=False),
            response=LexiconResponse.KNOW if arg == 1 else LexiconResponse.DONT,
            to_skip=False,
            time=dt(2000, 1, index + 1),
            request_time=dt(2000, 1, index + 1),
        )


def test_rate_empty(lexicon: Lexicon) -> None:
    """Test empty rate."""
    assert lexicon.construct_precise(precision=2) == ([], [])


def test_rate_zero_minimal(lexicon: Lexicon) -> None:
    """Test zero rate with minimal data."""

    register(lexicon, [0, 0])
    assert lexicon.construct_precise(precision=1) == (
        [(dt(2000, 1, 1), dt(2000, 1, 1)), (dt(2000, 1, 2), dt(2000, 1, 2))],
        [0.0, 0.0],
    )
    assert lexicon.construct_precise(precision=2) == (
        [(dt(2000, 1, 1), dt(2000, 1, 2))],
        [0.0],
    )


def test_rate_zero_additional(lexicon: Lexicon) -> None:
    """Test zero rate with additional data."""

    register(lexicon, [0, 0, 0])
    assert lexicon.construct_precise(precision=2) == (
        [(dt(2000, 1, 1), dt(2000, 1, 2)), (dt(2000, 1, 2), dt(2000, 1, 3))],
        [0.0, 0.0],
    )


def test_half_minimal(lexicon: Lexicon) -> None:
    """Test half minimal."""

    register(lexicon, [1, 0])
    assert lexicon.construct_precise(precision=1) == (
        [(dt(2000, 1, 1), dt(2000, 1, 2))],
        [1.0],
    )


def test_half_additional(lexicon: Lexicon) -> None:
    """Test half additional."""

    register(lexicon, [1, 0, 1, 0, 1, 0])

    assert lexicon.construct_precise(precision=2) == (
        [(dt(2000, 1, 1), dt(2000, 1, 4)), (dt(2000, 1, 3), dt(2000, 1, 6))],
        [1.0, 1.0],
    )
    assert lexicon.construct_precise(precision=1) == (
        [
            (dt(2000, 1, 1), dt(2000, 1, 2)),
            (dt(2000, 1, 3), dt(2000, 1, 4)),
            (dt(2000, 1, 5), dt(2000, 1, 6)),
        ],
        [1.0, 1.0, 1.0],
    )


def test_quarter_minimal(lexicon: Lexicon) -> None:
    """Test quarter minimal."""

    register(lexicon, [1, 1, 1, 0])
    assert lexicon.construct_precise(precision=1) == (
        [(dt(2000, 1, 1), dt(2000, 1, 4))],
        [2.0],
    )


# Strategy-aware rate estimators (see `research/metric.tex`): each selection
# strategy's log must be fed to its own estimator, dispatched by
# `estimate_rate_with_sd`.


def test_estimate_rate_frequency_window() -> None:
    """FWR uses the last window of `precision` unknowns: r = -log2(n/m)."""

    # 8 answers per unknown, repeated 10 times: theta = 1/8, r = 3.
    sequence: list[int] = [1, 1, 1, 1, 1, 1, 1, 0] * 10
    estimate = estimate_rate_frequency(sequence, precision=10)
    assert estimate is not None
    rate_value, sd = estimate
    assert rate_value == pytest.approx(3.0)
    assert sd == pytest.approx(1.0 / (math.log(2) * math.sqrt(10)))


def test_estimate_rate_frequency_whole_log_before_precision() -> None:
    """With fewer unknowns than `precision`, the whole log is the window."""

    sequence: list[int] = [1, 1, 1, 0] * 5  # 5 unknowns out of 20.
    estimate = estimate_rate_frequency(sequence, precision=100)
    assert estimate is not None
    rate_value, sd = estimate
    assert rate_value == pytest.approx(2.0)  # -log2(5 / 20).
    assert sd == pytest.approx(1.0 / (math.log(2) * math.sqrt(5)))


def test_estimate_rate_frequency_not_enough_data() -> None:
    """Fewer unknowns than the minimum yield no estimate."""

    assert estimate_rate_frequency([1, 1, 0, 1], precision=100) is None
    assert estimate_rate_frequency([], precision=100) is None


def test_estimate_rate_threshold_point_estimate() -> None:
    """OT: tested unknown mass plus untested mass above the boundary."""

    # 30 words, word at rank r has count 31 - r; total mass 465.
    total: float = 465.0
    tested: list[tuple[int, float, int]] = []
    untested: list[tuple[int, float]] = []
    tested_ranks: set[int] = set(range(1, 7)) | set(range(10, 16))
    for rank in range(1, 31):
        p_i: float = (31 - rank) / total
        if rank in tested_ranks:
            tested.append((rank, p_i, 0 if rank < 7 else 1))
        else:
            untested.append((rank, p_i))

    estimate = estimate_rate_threshold(tested, untested, n_bootstrap=50)
    assert estimate is not None
    rate_value, sd = estimate
    # Boundary i* is (6 + 10) // 2 = 8; theta is the mass of tested unknowns
    # (ranks 10..15, mass 111) plus the untested mass above rank 8 (ranks 9
    # and 16..30, mass 142), out of 465.
    assert rate_value == pytest.approx(-math.log2(253.0 / 465.0))
    assert sd >= 0.0


def test_estimate_rate_stratified_point_estimate() -> None:
    """SFWR: Horvitz-Thompson estimate over log-uniform strata."""

    # Ranks 1..4 with masses .4, .3, .2, .1; two strata: {1} and {2, 3, 4}.
    tested: list[tuple[int, float, int]] = [
        (1, 0.4, 0),
        (2, 0.3, 1),
        (3, 0.2, 0),
    ]
    untested: list[tuple[int, float]] = [(4, 0.1)]

    estimate = estimate_rate_stratified(tested, untested, n_strata=2)
    assert estimate is not None
    rate_value, sd = estimate
    # theta = P_0 * 0 + P_1 * (.3 / .5) = .6 * .6 = .36.
    assert rate_value == pytest.approx(-math.log2(0.36))
    assert sd > 0.0


def test_estimate_rate_stratified_requires_full_coverage() -> None:
    """SFWR yields no estimate while a stratum with mass is untested."""

    tested: list[tuple[int, float, int]] = [(1, 0.4, 0)]
    untested: list[tuple[int, float]] = [(2, 0.3), (3, 0.2), (4, 0.1)]

    assert estimate_rate_stratified(tested, untested, n_strata=2) is None


def test_estimate_rate_logistic_recovers_step_knowledge() -> None:
    """LA fits the logistic model and integrates it over untested words."""

    # 100 words, word at rank r has count 101 - r. Knowledge is a step at
    # rank 35: tested words below are known, above unknown.
    total: float = 5050.0
    tested: list[tuple[int, float, int]] = []
    untested: list[tuple[int, float]] = []
    tested_ranks: set[int] = set(range(1, 31, 2)) | set(range(40, 71, 2))
    for rank in range(1, 101):
        p_i: float = (101 - rank) / total
        if rank in tested_ranks:
            tested.append((rank, p_i, 0 if rank < 35 else 1))
        else:
            untested.append((rank, p_i))

    estimate = estimate_rate_logistic(tested, untested, n_bootstrap=20)
    assert estimate is not None
    rate_value, sd = estimate
    # True unknown mass (everything above rank 34) is 2211 / 5050, r = 1.19;
    # the smooth fit only needs to land in the right neighbourhood.
    assert 0.5 < rate_value < 2.5
    assert sd > 0.0


def test_estimate_rate_dispatches_by_selection() -> None:
    """The dispatcher routes each strategy's log to its own estimator."""

    sequence: list[int] = [1, 1, 1, 0] * 5
    assert estimate_rate_with_sd(
        "frequency", sequence=sequence
    ) == estimate_rate_frequency(sequence)

    frequency_list: FrequencyList = _ranked_frequency_list(30)
    states: dict[str, tuple[str | None, bool | None]] = {
        f"w{i}": (("K" if i < 6 else "D"), None)
        for i in list(range(6)) + list(range(9, 15))
    }
    estimate = estimate_rate_with_sd("threshold", frequency_list, states)
    assert estimate is not None
    # `w{i}` has rank i + 1, so this is the OT test case above.
    assert estimate[0] == pytest.approx(-math.log2(253.0 / 465.0))

    with pytest.raises(NotImplementedError):
        estimate_rate_with_sd("arbitrary", sequence=sequence)
