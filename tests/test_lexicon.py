from datetime import datetime
from pathlib import Path

import pytest

from emmio.lexicon.config import LexiconConfig, LexiconSelection
from emmio.lexicon.core import (
    Lexicon,
    LexiconLog,
    LexiconResponse,
    WordSelection,
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
    lexicon.register("apple", LexiconResponse.KNOW, False, datetime(2000, 1, 1))
    assert len(lexicon.responses) == 1
    assert lexicon.has("apple")
    assert lexicon.get("apple") == LexiconResponse.KNOW


def register(lexicon: Lexicon, args: list[int]) -> None:
    """Register."""
    for index, arg in enumerate(args):
        lexicon.register(
            "apple",
            LexiconResponse.KNOW if arg == 1 else LexiconResponse.DONT,
            False,
            datetime(2000, 1, index + 1),
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
