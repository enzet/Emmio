from pathlib import Path
from emmio.lists.config import FrequencyListConfig, FrequencyListFileFormat
from emmio.lists.frequency_list import FrequencyList

from unittest.mock import patch, mock_open
from textwrap import dedent
import pytest


@pytest.fixture
def empty_frequency_list() -> FrequencyList:
    """Create minimal frequency list."""
    return FrequencyList(
        file_path=Path("tests/data/test_frequency.txt"),
        config=FrequencyListConfig(
            path=Path("test_frequency.txt"),
            file_format=FrequencyListFileFormat.LIST,
            language="en",
            is_stripped=False,
        ),
    )


@pytest.fixture
def frequency_list_with_data(
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
    assert frequency_list_with_data._occurrences == 8


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

    def mock_file(file_path: Path, *args, **kwargs):
        if file_path.name == file_name:
            return mock_open(read_data=csv_content)(file_path, *args, **kwargs)
        else:
            raise FileNotFoundError(f"File `{file_path}` not found.")

    with (
        patch("pathlib.Path.exists") as mock_exists,
        patch("pathlib.Path.open", mock_file),
    ):
        mock_exists.return_value = True
        frequency_list: FrequencyList = FrequencyList(
            file_path=Path(file_name),
            config=FrequencyListConfig(
                path=Path(file_name),
                file_format=FrequencyListFileFormat.CSV,
                language="en",
                is_stripped=False,
                csv_header=["number", "word", "form", "count"],
                csv_delimiter=";",
            ),
        )
        frequency_list.load()
