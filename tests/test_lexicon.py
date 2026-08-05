"""Tests for lexicon."""

import asyncio
import math
import random
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from emmio.dictionary.core import DictionaryCollection
from emmio.language import KnownLanguages
from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    DEFAULT_N_STRATA,
    AnswerType,
    CuratedStratifiedSelector,
    Lexicon,
    LexiconChecker,
    LexiconLog,
    LexiconResponse,
    LogisticSelector,
    StratifiedSelector,
    TopSelector,
    _predict,
    _stratified_rate_from_aggregates,
    compute_lexicon_rate,
    create_selector,
    estimate_rate_frequency,
    estimate_rate_logistic,
    estimate_rate_stratified,
    estimate_rate_threshold,
    estimate_rate_with_sd,
    select_next_word,
    stratum_of_rank,
)
from emmio.lexicon.curation import classify_automatically
from emmio.lexicon.history import compute_rate_history
from emmio.lists.config import (
    FrequencyListConfig,
    FrequencyListFileFormat,
    ListUsageConfig,
)
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.data import SentencesData
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

    for selection in (LexiconSelection.FREQUENCY, LexiconSelection.RANDOM):
        word = select_next_word(frequency_list, {"the", "cat"}, selection)
        assert word == "dog"  # Only unanswered word.
        assert select_next_word(frequency_list, words, selection) is None
        assert select_next_word(frequency_list, set(), selection) in words


def test_select_next_word_rejects_unsupported_strategy() -> None:
    """Strategies not served over the API raise."""

    frequency_list: FrequencyList = _frequency_list({"the": 100})

    with pytest.raises(NotImplementedError):
        select_next_word(frequency_list, set(), LexiconSelection.ARBITRARY)


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

    assert select_next_word(frequency_list, set(), LexiconSelection.TOP) == "w0"
    assert (
        select_next_word(frequency_list, {"w0", "w1"}, LexiconSelection.TOP)
        == "w2"
    )


def test_select_next_word_threshold_targets_the_boundary() -> None:
    """`threshold` picks an untested word near the known/unknown boundary."""

    frequency_list: FrequencyList = _ranked_frequency_list(20)
    # Words below rank ~10 are known, above are unknown; w9/w10 are untested.
    states: dict[str, tuple[str | None, bool | None]] = {}
    for i in range(20):
        if i in (9, 10):
            continue
        states[f"w{i}"] = (("K" if i < 10 else "D"), None)

    word = select_next_word(
        frequency_list, set(), LexiconSelection.THRESHOLD, states
    )
    assert word in {"w9", "w10"}


def test_select_stratified_covers_untested_strata_first() -> None:
    """SFWR surveys every stratum before refining any.

    An untested stratum has infinite marginal value, so it is queried even
    when a tested stratum is maximally mixed (which would win under a
    non-marginal score).
    """
    # 16 words, 2 strata: ranks 1-3 (w0-w2) and 4-16 (w3-w15).
    frequency_list: FrequencyList = _ranked_frequency_list(16)
    states: dict[str, tuple[str | None, bool | None]] = {
        "w0": ("K", None),
        "w1": ("D", None),
    }

    word = StratifiedSelector(frequency_list, states, n_strata=2).next_word()
    assert word in {f"w{i}" for i in range(3, 16)}


def test_select_stratified_prefers_marginal_variance_reduction() -> None:
    """SFWR refines the stratum whose next query reduces variance the most.

    A lightly tested all-known stratum (Laplace-smoothed uncertainty, n=1)
    beats a heavily tested mixed one (n=4): the raw score would freeze the
    former at zero and dwell in the latter forever.
    """
    frequency_list: FrequencyList = _ranked_frequency_list(16)
    states: dict[str, tuple[str | None, bool | None]] = {
        "w0": ("K", None),  # Stratum 0: n=1, all known.
        "w3": ("K", None),  # Stratum 1: n=4, mixed.
        "w4": ("D", None),
        "w5": ("K", None),
        "w6": ("D", None),
    }

    word = StratifiedSelector(frequency_list, states, n_strata=2).next_word()
    assert word in {"w1", "w2"}


def test_select_stratified_draws_within_stratum_at_random() -> None:
    """SFWR draws uniformly within the stratum, not a front-sweep.

    The deterministic highest-frequency pick would return the same word every
    time, sampling the stratum from its most-known edge.
    """
    frequency_list: FrequencyList = _ranked_frequency_list(16)
    states: dict[str, tuple[str | None, bool | None]] = {
        "w0": ("K", None),
        "w4": ("D", None),
    }

    random.seed(0)
    picks: set[str | None] = {
        StratifiedSelector(frequency_list, states, n_strata=2).next_word()
        for _ in range(30)
    }
    assert len(picks) > 1


def test_curated_stratified_only_draws_from_curated_pool() -> None:
    """A curated-backed selector never draws a word outside the panel.

    `w1` and `w2` are untested in the raw list and stratum 0's rank range,
    but only `w1` is in the curated panel; the raw `StratifiedSelector`
    would be free to draw either, but the curated one must always return
    `w1`.
    """
    frequency_list: FrequencyList = _ranked_frequency_list(16)
    selector = CuratedStratifiedSelector(
        frequency_list,
        {},
        {0: ["w1"], 1: [f"w{i}" for i in range(3, 16)]},
        n_strata=2,
    )
    for _ in range(20):
        assert selector.next_word() in {"w1", *(f"w{i}" for i in range(3, 16))}


def test_curated_stratified_ignores_answers_outside_the_panel() -> None:
    """An answer for a word outside the panel does not affect bookkeeping.

    `w0` is answered but not part of the curated panel (e.g. propagated from
    a sibling lexicon over the same raw list); the base `StratifiedSelector`
    would count it toward stratum 0's tested statistics (it falls in that
    rank range), but the curated one must ignore it entirely, so stratum 0
    still looks fully untested (`_untested_count` equals the panel size, not
    the panel size minus one).
    """
    frequency_list: FrequencyList = _ranked_frequency_list(16)
    states: dict[str, tuple[str | None, bool | None]] = {"w0": ("K", None)}
    selector = CuratedStratifiedSelector(
        frequency_list,
        states,
        {0: ["w1"], 1: [f"w{i}" for i in range(3, 16)]},
        n_strata=2,
    )
    assert selector._untested_count(0) == 1  # noqa: SLF001


def test_curated_stratified_covers_untested_strata_first() -> None:
    """Coverage-first behavior still holds when restricted to a panel."""

    frequency_list: FrequencyList = _ranked_frequency_list(16)
    states: dict[str, tuple[str | None, bool | None]] = {"w4": ("K", None)}
    selector = CuratedStratifiedSelector(
        frequency_list, states, {0: ["w1"], 1: ["w4", "w5", "w6"]}, n_strata=2
    )
    assert selector.next_word() == "w1"


def test_select_next_word_curated_stratified_via_create_selector() -> None:
    """`select_next_word`/`create_selector` wire the curated pool through."""

    frequency_list: FrequencyList = _ranked_frequency_list(16)
    word = select_next_word(
        frequency_list,
        set(),
        LexiconSelection.STRATIFIED,
        n_strata=2,
        curated_words_by_stratum={0: ["w1"], 1: ["w5"]},
    )
    assert word in {"w1", "w5"}


def test_select_next_word_model_strategies_skip_answered() -> None:
    """Model strategies never re-pick a word that already has a response."""

    frequency_list: FrequencyList = _ranked_frequency_list(6)
    states: dict[str, tuple[str | None, bool | None]] = {
        f"w{i}": (("K" if i % 2 else "D"), None) for i in range(5)
    }  # Only `w5` is untested.

    for strategy in (
        LexiconSelection.LOGISTIC,
        LexiconSelection.THRESHOLD,
        LexiconSelection.STRATIFIED,
    ):
        assert select_next_word(frequency_list, set(), strategy, states) == "w5"


def _make_lexicon(language: str) -> Lexicon:
    """Build a bare lexicon for the given language code, own log."""

    with tempfile.TemporaryDirectory() as temp_directory:
        lexicon_instance: Lexicon = Lexicon.from_config(
            Path(temp_directory),
            language,
            LexiconConfig(
                language=language,
                frequency_list=ListUsageConfig(id=language),
                selection=LexiconSelection.ARBITRARY,
            ),
            "test",
        )
        lexicon_instance.log = LexiconLog()
        return lexicon_instance


@pytest.fixture(name="lexicon")
def fixture_lexicon() -> Lexicon:
    """Test lexicon checking process."""

    return _make_lexicon("en")


def _make_checker(lexicon_instance: Lexicon) -> LexiconChecker:
    """Build a `LexiconChecker` around `lexicon_instance`.

    `do_skip` only touches `lexicon`/`interface`/`skip_known`/`skip_unknown`
    and whatever is passed explicitly (`other_lexicons`, `frequency_list`);
    the dictionary/sentence collaborators are real-but-empty, since
    `beartype` enforces their declared types at construction time.
    """
    with tempfile.TemporaryDirectory() as temp_directory:
        sentences_path: Path = Path(temp_directory) / "sentences"
        (sentences_path / "cache").mkdir(parents=True)
        return LexiconChecker(
            interface=TerminalInterface(use_input=False),
            lexicon=lexicon_instance,
            dictionaries=DictionaryCollection(),
            sentences_data=SentencesData.from_config(sentences_path),
            sentences_usage_configs=[],
        )


def test_answer_type_proper_noun_code_round_trips() -> None:
    """The proper-noun assume answer type persists and reloads."""

    code = AnswerType.ASSUME__NOT_A_WORD__PROPER.to_code()
    assert code is not None
    assert AnswerType.from_code(code) == AnswerType.ASSUME__NOT_A_WORD__PROPER


def test_do_skip_assumes_proper_noun_from_cap_ratio(lexicon: Lexicon) -> None:
    """High `cap_ratio`, not a curated exception: auto-marked not-a-word."""

    frequency_list: FrequencyList = _frequency_list({"paris": 100})
    frequency_list.cap_ratios["paris"] = 0.95

    checker: LexiconChecker = _make_checker(lexicon)
    assert checker.do_skip("paris", [], frequency_list) is True
    assert lexicon.get("paris") == LexiconResponse.NOT_A_WORD
    assert (
        lexicon.get_records("paris")[-1].answer_type
        == AnswerType.ASSUME__NOT_A_WORD__PROPER
    )


def test_do_skip_below_threshold_is_not_assumed(lexicon: Lexicon) -> None:
    """A word with `cap_ratio` at or below the threshold is left alone."""

    frequency_list: FrequencyList = _frequency_list({"often": 100})
    frequency_list.cap_ratios["often"] = 0.8

    checker: LexiconChecker = _make_checker(lexicon)
    assert checker.do_skip("often", [], frequency_list) is False
    assert not lexicon.has("often")


def test_do_skip_respects_non_proper_nouns_exception() -> None:
    """A curated exception (French `unis`) is never auto-assumed."""

    lexicon_fr: Lexicon = _make_lexicon("fr")
    frequency_list: FrequencyList = _frequency_list({"unis": 100})
    frequency_list.cap_ratios["unis"] = 0.95

    checker: LexiconChecker = _make_checker(lexicon_fr)
    assert checker.do_skip("unis", [], frequency_list) is False
    assert not lexicon_fr.has("unis")


def test_do_skip_disables_proper_noun_check_for_german() -> None:
    """German capitalizes every noun, so `cap_ratio` must be ignored there.

    Same shape as `test_do_skip_assumes_proper_noun_from_cap_ratio` (a
    high `cap_ratio`, no curated exception needed) — for most languages
    this would auto-mark the word not-a-word; for German it must not,
    since `Fenster` (window) is capitalized every bit as consistently as
    an actual proper noun would be.
    """

    lexicon_de: Lexicon = _make_lexicon("de")
    frequency_list: FrequencyList = _frequency_list({"fenster": 100})
    frequency_list.cap_ratios["fenster"] = 0.95

    checker: LexiconChecker = _make_checker(lexicon_de)
    assert checker.do_skip("fenster", [], frequency_list) is False
    assert not lexicon_de.has("fenster")


def test_do_skip_without_frequency_list_disables_proper_noun_check(
    lexicon: Lexicon,
) -> None:
    """Without a `frequency_list`, `cap_ratio` is unavailable: never assumed."""

    checker: LexiconChecker = _make_checker(lexicon)
    assert checker.do_skip("paris", [], None) is False
    assert not lexicon.has("paris")


def test_classify_automatically_assumes_proper_noun_from_cap_ratio() -> None:
    """`classify_automatically` mirrors `do_skip`'s "P" (proper noun) call."""

    frequency_list: FrequencyList = _frequency_list({"paris": 100})
    frequency_list.cap_ratios["paris"] = 0.95

    category = asyncio.run(
        classify_automatically(
            "paris",
            KnownLanguages.FRENCH,
            None,
            frequency_list,
            frozenset(),
            DictionaryCollection(),
        )
    )
    assert category == "P"


def test_classify_automatically_disables_proper_noun_check_for_german() -> None:
    """Same fix as `test_do_skip_disables_proper_noun_check_for_german`.

    `classify_automatically` is a separate function from `do_skip` (shared
    only through `CAP_RATIO_UNSUPPORTED_LANGUAGES`), so it needs its own
    regression coverage: without a dictionary hit either way, an
    undecided word is left `None` (for a human curator), not misclassified
    as `"P"`.
    """

    frequency_list: FrequencyList = _frequency_list({"fenster": 100})
    frequency_list.cap_ratios["fenster"] = 0.95

    category = asyncio.run(
        classify_automatically(
            "fenster",
            KnownLanguages.GERMAN,
            None,
            frequency_list,
            frozenset(),
            DictionaryCollection(),
        )
    )
    assert category is None


@pytest.mark.parametrize(
    ("word", "origin"),
    [
        ("paris", AnswerType.ASSUME__NOT_A_WORD__PROPER),
        ("xyzzy", AnswerType.ASSUME__NOT_A_WORD__ALPHABET),
    ],
)
def test_do_skip_propagates_not_a_word_as_generic(
    lexicon: Lexicon, word: str, origin: AnswerType
) -> None:
    """Propagation always uses the generic answer type."""

    other: Lexicon = _make_lexicon("en")
    other.register(
        word=word,
        interface=TerminalInterface(use_input=False),
        response=LexiconResponse.NOT_A_WORD,
        to_skip=None,
        time=dt(2000, 1, 1),
        request_time=dt(2000, 1, 1),
        answer_type=origin,
    )

    checker: LexiconChecker = _make_checker(lexicon)
    assert checker.do_skip(word, [other]) is True
    assert lexicon.get(word) == LexiconResponse.NOT_A_WORD
    assert (
        lexicon.get_records(word)[-1].answer_type
        == AnswerType.PROPAGATE__NOT_A_WORD
    )


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


def test_know_semantic_class_code_round_trip() -> None:
    """`KNOW_SEMANTIC_CLASS` persists as `C` and round-trips through it."""

    assert LexiconResponse.KNOW_SEMANTIC_CLASS.to_code() == "C"
    assert LexiconResponse.from_code("C") == LexiconResponse.KNOW_SEMANTIC_CLASS


def test_register_know_semantic_class_counts_as_know(lexicon: Lexicon) -> None:
    """Recognizing a word's class but not its exact meaning counts as known."""

    lexicon.register(
        word="strawberry",
        interface=TerminalInterface(use_input=False),
        response=LexiconResponse.KNOW_SEMANTIC_CLASS,
        to_skip=False,
        time=dt(2000, 1, 1),
        request_time=dt(2000, 1, 1),
    )
    assert lexicon.responses == [1]
    assert lexicon.know("strawberry")
    assert lexicon.get("strawberry") == LexiconResponse.KNOW_SEMANTIC_CLASS


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


def test_estimate_rate_stratified_census_has_zero_sd() -> None:
    """SFWR: a fully tested list is a census, with no sampling uncertainty.

    Without the finite population correction the Laplace-smoothed variance
    never reaches zero, freezing the SD once small strata are exhausted.
    """

    tested: list[tuple[int, float, int]] = [
        (1, 0.4, 0),
        (2, 0.3, 1),
        (3, 0.2, 0),
        (4, 0.1, 1),
    ]

    estimate = estimate_rate_stratified(tested, [], n_strata=2)
    assert estimate is not None
    rate_value, sd = estimate
    assert rate_value == pytest.approx(-math.log2(0.4))
    assert sd == 0.0


def test_estimate_rate_stratified_resolved_words_shrink_population() -> None:
    """SFWR: resolved words are untestable, so they never carry uncertainty.

    A stratum whose every learnable word is tested is a census even when
    resolved (unlearnable) words remain in its rank range.
    """

    tested: list[tuple[int, float, int]] = [
        (1, 0.4, 0),
        (2, 0.3, 1),
        (3, 0.2, 0),
    ]
    resolved: list[tuple[int, float]] = [(4, 0.1)]

    estimate = estimate_rate_stratified(
        tested, [], resolved=resolved, n_strata=2
    )
    assert estimate is not None
    _, sd = estimate
    assert sd == 0.0

    # The same stratum with an untested word instead is not a census.
    estimate = estimate_rate_stratified(tested, [(4, 0.1)], n_strata=2)
    assert estimate is not None
    _, sd = estimate
    assert sd > 0.0


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
        LexiconSelection.FREQUENCY, sequence=sequence
    ) == estimate_rate_frequency(sequence)

    frequency_list: FrequencyList = _ranked_frequency_list(30)
    states: dict[str, tuple[str | None, bool | None]] = {
        f"w{i}": (("K" if i < 6 else "D"), None)
        for i in list(range(6)) + list(range(9, 15))
    }
    estimate = estimate_rate_with_sd(
        LexiconSelection.THRESHOLD, frequency_list, states
    )
    assert estimate is not None
    # `w{i}` has rank i + 1, so this is the OT test case above.
    assert estimate[0] == pytest.approx(-math.log2(253.0 / 465.0))

    with pytest.raises(NotImplementedError):
        estimate_rate_with_sd(LexiconSelection.ARBITRARY, sequence=sequence)


def test_stratified_rate_from_aggregates_uses_stratum_size_for_fpc() -> None:
    """The finite-population correction scales with the given `stratum_size`.

    Same tested aggregates, two different `stratum_size` values for the one
    stratum carrying data: the raw list's inflated width (nowhere near
    exhausted by 10 tested words) keeps the FPC well above zero, while the
    curated panel's true size (already exhausted by `count`) drops that
    stratum's variance contribution to zero — so the correct (small)
    population must yield a strictly smaller SD, not a larger one (the
    direction the pre-fix bug got backwards).
    """
    p_total: list[float] = [1.0]
    p_tested: list[float] = [1.0]
    p_unknown: list[float] = [0.3]
    count: list[int] = [10]
    count_unknown: list[int] = [3]

    raw = _stratified_rate_from_aggregates(
        p_total, p_tested, p_unknown, count, count_unknown, [100_000]
    )
    curated = _stratified_rate_from_aggregates(
        p_total, p_tested, p_unknown, count, count_unknown, [10]
    )
    assert raw is not None
    assert curated is not None
    assert raw[0] == curated[0]  # The point estimate never depends on N_k.
    assert raw[1] > 0.0
    assert curated[1] == 0.0  # An exhausted panel is a census: no variance.
    assert curated[1] < raw[1]


def test_estimate_rate_curated_lowers_sd_via_correct_population() -> None:
    """A curated lexicon's SD uses the panel's population, not the raw list's.

    Same tested words either way (a fully-tested, tiny curated panel); only
    `curated_words_by_stratum` differs. Treating the raw list's rank-range
    width as the population (the pre-fix behavior) keeps the finite
    population correction well above zero even though the panel itself is
    fully surveyed; using the panel's own size correctly recognizes the
    census and drops the SD.
    """
    frequency_list: FrequencyList = _ranked_frequency_list(1000)
    n_strata = 2

    panel_by_stratum: dict[int, list[str]] = {0: [], 1: []}
    for rank in range(1, 1001):
        k = stratum_of_rank(rank, 1000, n_strata)
        if len(panel_by_stratum[k]) < 2:
            panel_by_stratum[k].append(f"w{rank - 1}")
        if all(len(words) >= 2 for words in panel_by_stratum.values()):
            break

    states: dict[str, tuple[str | None, bool | None]] = {
        word: (("K" if index == 0 else "D"), None)
        for words in panel_by_stratum.values()
        for index, word in enumerate(words)
    }

    raw = estimate_rate_with_sd(
        LexiconSelection.STRATIFIED, frequency_list, states, n_strata=n_strata
    )
    curated = estimate_rate_with_sd(
        LexiconSelection.STRATIFIED,
        frequency_list,
        states,
        n_strata=n_strata,
        curated_words_by_stratum=panel_by_stratum,
    )
    assert raw is not None
    assert curated is not None
    assert curated[0] == raw[0]  # Point estimate unaffected.
    assert curated[1] == 0.0  # Every panel stratum is a fully tested census.
    assert curated[1] < raw[1]


def test_selectors_incremental_matches_rebuilt() -> None:
    """Recording answers one by one equals rebuilding from scratch.

    The selector is a session's working memory; its draws must match what a
    stateless caller would get from the same ground truth. `top` and
    `threshold` are deterministic, so words must be equal; for `stratified`
    the draw within the stratum is random, so the chosen stratum must be
    equal. Random-driven paths are seeded identically on both sides.
    """
    size: int = 64
    frequency_list: FrequencyList = _ranked_frequency_list(size)

    def code(word: str) -> str:
        # Words in the top half of the list (by rank) are known.
        return "K" if int(word[1:]) < size // 2 else "D"

    for strategy in (
        LexiconSelection.TOP,
        LexiconSelection.THRESHOLD,
        LexiconSelection.STRATIFIED,
    ):
        incremental = create_selector(frequency_list, strategy, {})
        states: dict[str, tuple[str | None, bool | None]] = {}
        answered: set[str] = set()
        for step in range(20):
            random.seed(step)
            picked: str | None = incremental.next_word()
            assert picked is not None
            fresh = create_selector(
                frequency_list, strategy, dict(states), set(answered)
            )
            random.seed(step)
            expected: str | None = fresh.next_word()
            assert expected is not None
            if strategy == LexiconSelection.STRATIFIED:
                rank = frequency_list.get_index(picked) + 1
                expected_rank = frequency_list.get_index(expected) + 1
                assert stratum_of_rank(rank, size) == stratum_of_rank(
                    expected_rank, size
                ), f"{strategy}, step {step}"
            else:
                assert picked == expected, f"{strategy}, step {step}"
            states[picked] = (code(picked), None)
            answered.add(picked)
            incremental.record(picked, code(picked))


def test_logistic_selector_explore_matches_rebuilt() -> None:
    """Before the model is fittable, LA explores identically to a rebuild."""
    frequency_list: FrequencyList = _ranked_frequency_list(64)
    incremental = LogisticSelector(frequency_list, {})
    states: dict[str, tuple[str | None, bool | None]] = {}
    for step in range(10):
        # Seeding must happen after construction: the runtime type checker
        # (beartype) samples container arguments randomly during calls.
        fresh = LogisticSelector(frequency_list, dict(states))
        random.seed(step)
        picked: str | None = incremental.next_word()
        assert picked is not None
        random.seed(step)
        expected = fresh.next_word()
        assert picked == expected, f"step {step}"
        # Alternate known/unknown so the model stays unfittable (few unknown).
        code = "K" if step % 3 else "D"
        states[picked] = (code, None)
        incremental.record(picked, code)


def test_logistic_selector_exploits_the_highest_score() -> None:
    """With a fitted model, LA picks the argmax of p_i² · π (1 − π)."""
    size: int = 40
    frequency_list: FrequencyList = _ranked_frequency_list(size)
    # Enough data to fit: low ranks known, high ranks unknown.
    states: dict[str, tuple[str | None, bool | None]] = {
        f"w{i}": ("K" if i < 10 else "D", None)
        for i in list(range(10)) + list(range(30, 38))
    }
    selector = LogisticSelector(frequency_list, states)
    picked: str | None = selector.next_word()
    assert picked is not None

    params = selector.fit()
    assert params is not None
    a, b, c = params
    total: int = frequency_list.get_all_occurrences()
    best_word: str | None = None
    best_score: float = -1.0
    for rank, word in enumerate(frequency_list.get_words(), start=1):
        if word in states:
            continue
        p_i: float = frequency_list.get_occurrences(word) / total
        pi_i: float = _predict(a, b, c, rank)
        score: float = p_i**2 * pi_i * (1.0 - pi_i)
        if score > best_score:
            best_score = score
            best_word = word
    assert picked == best_word


def test_stratified_selector_never_repeats_or_leaks_excluded() -> None:
    """SFWR draws are always untested and respect per-draw exclusion."""

    frequency_list: FrequencyList = _ranked_frequency_list(32)
    selector = StratifiedSelector(frequency_list, {}, n_strata=2)
    seen: set[str] = set()
    for _ in range(32):
        word: str | None = selector.next_word(exclude=seen)
        if word is None:
            break
        assert word not in seen
        seen.add(word)
        selector.record(word, "D")
    assert len(seen) == 32  # Exhausts the list exactly once.
    assert selector.next_word() is None


def test_selector_record_handles_word_transitions() -> None:
    """Re-answering a word (know → don't know) retallies, not double-counts."""

    frequency_list: FrequencyList = _ranked_frequency_list(16)
    selector = StratifiedSelector(frequency_list, {}, n_strata=2)
    selector.record("w0", "K")
    selector.record("w0", "D")
    selector.record("w0", "D")  # Same answer again: no-op.
    theta_k: list[float] = selector.theta_by_stratum()
    assert theta_k[0] == 1.0  # The only tested word in stratum 0 is unknown.


def test_top_selector_draws_sibling_answered_words_once() -> None:
    """`top` re-draws words answered elsewhere until they are recorded here."""
    frequency_list: FrequencyList = _ranked_frequency_list(4)
    selector = TopSelector(frequency_list, {"w0"})
    assert selector.next_word() == "w1"
    # `w1` was answered in a sibling lexicon: the caller records the
    # propagated answer, and the selector moves on.
    selector.record("w1", "K")
    assert selector.next_word() == "w2"


def _dated(records: list[tuple[str, str]]) -> list[tuple[datetime, str, str]]:
    """Spread (word, response code) records one hour apart, oldest first."""
    return [
        (dt(2024, 1, 1) + timedelta(hours=hour), word, code)
        for hour, (word, code) in enumerate(records)
    ]


def test_compute_rate_history_frequency_matches_classic_windows() -> None:
    """The default threshold reproduces the 100-don't-know FWR windows."""
    records: list[tuple[str, str]] = [
        (f"w{index}", "D" if index % 3 == 0 else "K") for index in range(400)
    ]
    records.insert(200, ("junk", "N"))  # Resolutions are not answers.
    dated: list[tuple[datetime, str, str]] = _dated(records)

    queries, date_ranges, rates, sds = compute_rate_history(
        LexiconSelection.FREQUENCY, None, dated
    )

    data: list[tuple[datetime, int]] = [
        (date, 1 if code == "K" else 0)
        for date, _, code in dated
        if code in ("K", "D")
    ]
    expected_ranges, expected_rates = compute_lexicon_rate(data, 100)
    assert date_ranges == expected_ranges
    assert rates == expected_rates
    assert all(sd == pytest.approx(1.0 / (math.log(2) * 10.0)) for sd in sds)
    # Every point's `queries` is the 1-based position of its window's end
    # date within the full (unfiltered) log.
    by_date: dict[datetime, int] = {
        date: position for position, (date, _, _) in enumerate(dated, start=1)
    }
    assert queries == [by_date[end] for _, end in date_ranges]


def test_compute_rate_history_frequency_threshold_sets_window() -> None:
    """A looser SD threshold shrinks the required unknown count."""
    dated: list[tuple[datetime, str, str]] = _dated(
        [(f"w{index}", "D" if index % 3 == 0 else "K") for index in range(100)]
    )
    sd_threshold: float = 1.0 / (math.log(2) * math.sqrt(25))

    _, date_ranges, rates, sds = compute_rate_history(
        LexiconSelection.FREQUENCY, None, dated, sd_threshold=sd_threshold
    )

    data: list[tuple[datetime, int]] = [
        (date, 1 if code == "K" else 0) for date, _, code in dated
    ]
    expected_ranges, expected_rates = compute_lexicon_rate(data, 25)
    assert date_ranges == expected_ranges
    assert rates == expected_rates
    assert all(sd == pytest.approx(sd_threshold) for sd in sds)


def test_compute_rate_history_stratified_census() -> None:
    """A censused list yields an exact point; noisier prefixes yield none."""
    frequency_list: FrequencyList = _frequency_list(
        {"a": 8, "b": 4, "c": 2, "d": 1}
    )
    dated: list[tuple[datetime, str, str]] = _dated(
        [("a", "K"), ("b", "K"), ("c", "D"), ("d", "K")]
    )

    queries, date_ranges, rates, sds = compute_rate_history(
        LexiconSelection.STRATIFIED, frequency_list, dated, n_strata=2
    )

    # Every point before the census has SD over the threshold; the census
    # has none: θ̂ is the unknown mass share of `c`.
    assert rates == [pytest.approx(-math.log2(2 / 15))]
    assert sds == [0.0]
    assert date_ranges == [(dated[0][0], dated[3][0])]
    assert queries == [4]  # The census completes at the 4th record.


def test_compute_rate_history_stratified_reask_uses_latest_answer() -> None:
    """Within a window, only a word's latest answer counts."""
    frequency_list: FrequencyList = _frequency_list(
        {"a": 8, "b": 4, "c": 2, "d": 1}
    )
    dated: list[tuple[datetime, str, str]] = _dated(
        [("a", "K"), ("b", "K"), ("c", "D"), ("d", "K"), ("d", "D")]
    )

    queries, date_ranges, rates, sds = compute_rate_history(
        LexiconSelection.STRATIFIED, frequency_list, dated, n_strata=2
    )

    # The re-ask flips `d` to unknown: still a census (no double count),
    # with the unknown mass share now covering `c` and `d`.
    assert len(rates) == 2
    assert rates[1] == pytest.approx(-math.log2(3 / 15))
    assert sds[1] == 0.0
    assert date_ranges[1] == (dated[0][0], dated[4][0])
    assert queries[1] == 5  # The re-ask is the 5th record.


def test_compute_rate_history_stratified_window_skips_superseded() -> None:
    """The window's left edge slides past superseded answers for free."""
    frequency_list: FrequencyList = _frequency_list(
        {"a": 8, "b": 4, "c": 2, "d": 1}
    )
    dated: list[tuple[datetime, str, str]] = _dated(
        [("a", "K"), ("b", "K"), ("c", "D"), ("d", "K"), ("a", "K")]
    )

    queries, date_ranges, rates, _ = compute_rate_history(
        LexiconSelection.STRATIFIED, frequency_list, dated, n_strata=2
    )

    # The re-ask supersedes the first answer for `a`, so the window starts
    # at `b`; dropping `b` itself would push the SD over the threshold.
    assert len(rates) == 2
    assert rates[1] == pytest.approx(-math.log2(2 / 15))
    assert date_ranges[1] == (dated[1][0], dated[4][0])
    assert queries[1] == 5  # The re-ask of `a` is the 5th record.


def test_compute_rate_history_stratified_resolution_is_permanent() -> None:
    """A resolution shrinks the population and never expires."""
    frequency_list: FrequencyList = _frequency_list(
        {"a": 8, "b": 4, "c": 2, "d": 1}
    )
    dated: list[tuple[datetime, str, str]] = _dated(
        [("a", "K"), ("b", "K"), ("c", "D"), ("d", "K"), ("d", "N"), ("b", "K")]
    )

    queries, date_ranges, rates, sds = compute_rate_history(
        LexiconSelection.STRATIFIED, frequency_list, dated, n_strata=2
    )

    # The resolution itself emits no point; after it, `d` is out of the
    # population, so the remaining words form a census again. Its frequency
    # mass still counts toward the stratum total.
    assert len(rates) == 2
    assert rates[1] == pytest.approx(-math.log2(7 / 45))
    assert sds[1] == 0.0
    assert date_ranges[1] == (dated[0][0], dated[5][0])
    assert queries[1] == 6  # The re-ask of `b` is the 6th record.


def test_compute_rate_history_no_backend_for_logistic() -> None:
    """Estimators with bootstrapped SDs have no windowed history yet."""
    with pytest.raises(NotImplementedError):
        compute_rate_history(LexiconSelection.LOGISTIC, None, [])
