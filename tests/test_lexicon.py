from datetime import datetime
from pathlib import Path

import pytest

from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    Lexicon,
    LexiconLog,
    LexiconResponse,
)


@pytest.fixture
def lexicon() -> Lexicon:
    """Test lexicon checking process."""
    temp_directory: Path = Path("/tmp") / "emmio_test_temp_directory"
    temp_directory.mkdir(exist_ok=True)
    lexicon: Lexicon = Lexicon(
        temp_directory,
        LexiconConfig(
            file_name="en.json",
            language="en",
            frequency_list={"id": "en"},
            selection=LexiconSelection.ARBITRARY,
        ),
    )
    lexicon.log = LexiconLog()
    return lexicon


def test_register(lexicon: Lexicon) -> None:
    """Test register."""
    lexicon.register(
        word="apple",
        response=LexiconResponse.KNOW,
        to_skip=False,
        time=datetime(2000, 1, 1),
        request_time=datetime(2000, 1, 1),
    )
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW


def register(lexicon: Lexicon, args: list[int]) -> None:
    """Register."""
    for index, arg in enumerate(args):
        lexicon.register(
            word="apple",
            response=LexiconResponse.KNOW if arg == 1 else LexiconResponse.DONT,
            to_skip=False,
            time=datetime(2000, 1, index + 1),
            request_time=datetime(2000, 1, index + 1),
        )


def test_rate_empty(lexicon: Lexicon) -> None:
    """Test rate empty."""
    assert lexicon.construct_precise(precision=2) == ([], [])


def test_rate_zero_minimal(lexicon: Lexicon) -> None:
    """Test rate."""
    register(lexicon, [0, 0])
    assert lexicon.construct_precise(precision=1) == (
        [
            (datetime(2000, 1, 1), datetime(2000, 1, 1)),
            (datetime(2000, 1, 2), datetime(2000, 1, 2)),
        ],
        [0.0, 0.0],
    )
    assert lexicon.construct_precise(precision=2) == (
        [(datetime(2000, 1, 1), datetime(2000, 1, 2))],
        [0.0],
    )


def test_rate_zero_additional(lexicon: Lexicon) -> None:
    """Test rate with additional data."""
    register(lexicon, [0, 0, 0])
    assert lexicon.construct_precise(precision=2) == (
        [
            (datetime(2000, 1, 1), datetime(2000, 1, 2)),
            (datetime(2000, 1, 2), datetime(2000, 1, 3)),
        ],
        [0.0, 0.0],
    )


def test_half_minimal(lexicon: Lexicon) -> None:
    """Test half minimal."""
    register(lexicon, [1, 0])
    assert lexicon.construct_precise(precision=1) == (
        [(datetime(2000, 1, 1), datetime(2000, 1, 2))],
        [1.0],
    )


def test_half_additional(lexicon: Lexicon) -> None:
    """Test half additional."""

    register(lexicon, [1, 0, 1, 0, 1, 0])

    assert lexicon.construct_precise(precision=2) == (
        [
            (datetime(2000, 1, 1), datetime(2000, 1, 4)),
            (datetime(2000, 1, 3), datetime(2000, 1, 6)),
        ],
        [1.0, 1.0],
    )
    assert lexicon.construct_precise(precision=1) == (
        [
            (datetime(2000, 1, 1), datetime(2000, 1, 2)),
            (datetime(2000, 1, 3), datetime(2000, 1, 4)),
            (datetime(2000, 1, 5), datetime(2000, 1, 6)),
        ],
        [1.0, 1.0, 1.0],
    )


def test_quarter_minimal(lexicon: Lexicon) -> None:
    """Test quarter minimal."""
    register(lexicon, [1, 1, 1, 0])
    assert lexicon.construct_precise(precision=1) == (
        [(datetime(2000, 1, 1), datetime(2000, 1, 4))],
        [2.0],
    )
