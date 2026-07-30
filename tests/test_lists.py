"""Test for frequency and word lists."""

from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import mock_open, patch

import pytest

from emmio.lists.config import FrequencyListConfig
from emmio.lists.frequency_list import FrequencyList, FrequencyListFileFormat


@pytest.fixture(name="empty_frequency_list")
def fixture_empty_frequency_list() -> FrequencyList:
    """Create minimal frequency list."""

    return FrequencyList(
        file_path=Path("tests", "data", "test_frequency.txt"),
        config=FrequencyListConfig(
            path="test_frequency.txt",
            file_format=FrequencyListFileFormat.LIST,
            language="en",
            is_stripped=False,
        ),
        data={},
    )


@pytest.fixture(name="frequency_list_with_data")
def fixture_frequency_list_with_data(
    empty_frequency_list: FrequencyList,
) -> FrequencyList:
    """Create a frequency list with data."""

    empty_frequency_list.add("test", 5)
    empty_frequency_list.add("word", 3)
    return empty_frequency_list


def test_data(frequency_list_with_data: FrequencyList) -> None:
    """Test `data` property."""

    assert frequency_list_with_data.data["test"] == 5
    assert frequency_list_with_data.data["word"] == 3


def test_has(frequency_list_with_data: FrequencyList) -> None:
    """Test `has()` method."""

    assert frequency_list_with_data.has("test") is True
    assert frequency_list_with_data.has("missing") is False


def test_get_occurrences(frequency_list_with_data: FrequencyList) -> None:
    """Test occurrences."""

    assert frequency_list_with_data.get_occurrences("test") == 5
    assert frequency_list_with_data.get_occurrences("word") == 3
    assert frequency_list_with_data.get_all_occurrences() == 8


def test_read_csv() -> None:
    """Test CSV frequency list reading.

    It is assumed that CSV files may contain word forms instead of just words.
    """
    file_name: str = "list.csv"
    csv_content: str = dedent(
        """
        1;book;noun;100
        2;book;verb;50
        """
    ).strip()

    def mock_file(file_path: Path, *args: Any, **kwargs: Any) -> Any:
        if file_path.name == file_name:
            return mock_open(read_data=csv_content)(file_path, *args, **kwargs)
        msg = f"File `{file_path}` not found."
        raise FileNotFoundError(msg)

    with (
        patch("pathlib.Path.exists") as mock_exists,
        patch("pathlib.Path.open", mock_file),
    ):
        mock_exists.return_value = True
        FrequencyList.from_config(
            path=Path("tests", "data"),
            config=FrequencyListConfig(
                path=file_name,
                file_format=FrequencyListFileFormat.CSV,
                language="en",
                is_stripped=False,
                csv_header=["number", "word", "form", "count"],
                csv_delimiter=";",
            ),
        )


def test_read_list_with_cap_ratio(tmp_path: Path) -> None:
    """`from_list_file` parses `freqlist`'s optional third `cap_ratio` field.

    `NA` (undefined ratio) and plain `word count` lines (the pre-`cap_ratio`
    format) both leave `get_cap_ratio` returning `None`, so old and new
    frequency lists remain interchangeable.
    """
    file_name: str = "list.txt"
    (tmp_path / file_name).write_text(
        dedent(
            """
            captain 3 0.33
            paris 2 1.00
            london 1 NA
            dog 1
            """
        ).strip()
        + "\n"
    )

    frequency_list: FrequencyList = FrequencyList.from_config(
        path=tmp_path,
        config=FrequencyListConfig(
            path=file_name,
            file_format=FrequencyListFileFormat.LIST,
            language="en",
            is_stripped=False,
        ),
    )

    assert frequency_list.get_occurrences("captain") == 3
    assert frequency_list.get_cap_ratio("captain") == pytest.approx(0.33)
    assert frequency_list.get_cap_ratio("paris") == pytest.approx(1.0)
    assert frequency_list.get_cap_ratio("london") is None
    assert frequency_list.get_cap_ratio("dog") is None
    assert frequency_list.get_cap_ratio("missing") is None


def _make_list(data: dict[str, int]) -> FrequencyList:
    """Build an in-memory frequency list."""
    return FrequencyList(
        file_path=Path("unused"),
        config=FrequencyListConfig(
            path="unused",
            file_format=FrequencyListFileFormat.LIST,
            language="en",
            is_stripped=False,
        ),
        data=data,
    )


def test_get_index_uses_rank_order() -> None:
    """Word lookup follows frequency order and misses return -1."""

    frequency_list: FrequencyList = _make_list({"a": 30, "b": 20, "c": 10})
    assert [frequency_list.get_index(word) for word in "abc"] == [0, 1, 2]
    assert frequency_list.get_index("missing") == -1


def test_get_range_occurrences_sums_by_rank() -> None:
    """Range sums match direct summation over the sorted order."""

    frequency_list: FrequencyList = _make_list(
        {f"w{i}": 100 - i for i in range(10)}
    )
    counts: list[int] = [100 - i for i in range(10)]
    assert frequency_list.get_range_occurrences(0, 10) == sum(counts)
    assert frequency_list.get_range_occurrences(2, 5) == sum(counts[2:5])
    assert frequency_list.get_range_occurrences(5, 5) == 0
    assert frequency_list.get_range_occurrences(8, 99) == sum(counts[8:])


def test_add_invalidates_derived_caches() -> None:
    """Mutating the list drops the rank index and cumulative sums."""

    frequency_list: FrequencyList = _make_list({"a": 30, "b": 20})
    assert frequency_list.get_index("b") == 1  # Builds the caches.
    frequency_list.derived["probe"] = True

    frequency_list.add("c", 40)  # Now the most frequent word.

    assert frequency_list.get_index("c") == 0
    assert frequency_list.get_index("b") == 2
    assert "probe" not in frequency_list.derived
    assert frequency_list.get_range_occurrences(0, 3) == 90


def test_random_word_by_frequency_is_valid() -> None:
    """Frequency-weighted draws return real words with their counts."""

    frequency_list: FrequencyList = _make_list({"a": 98, "b": 1, "c": 1})
    counter: dict[str, int] = {}
    for _ in range(200):
        word, occurrences = frequency_list.get_random_word_by_frequency()
        assert frequency_list.get_occurrences(word) == occurrences
        counter[word] = counter.get(word, 0) + 1
    # The dominant word must dominate the draws.
    assert counter["a"] > 150
