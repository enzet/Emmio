"""Tests for lexicon."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    Lexicon,
    LexiconLog,
    LexiconResponse,
    select_next_word,
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
    """Strategies not yet served over the API raise."""

    frequency_list: FrequencyList = _frequency_list({"the": 100})

    with pytest.raises(NotImplementedError):
        select_next_word(frequency_list, set(), "logistic")


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
