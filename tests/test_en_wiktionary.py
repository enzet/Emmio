"""Test for English Wiktionary."""

from emmio.dictionary.en_wiktionary import get_file_name


def test_file_name_lower() -> None:
    """Test file name that starts with a lowercase letter."""
    assert get_file_name("rücken") == "rücken.json"


def test_file_name_upper() -> None:
    """Test file name that starts with an uppercase letter."""
    assert get_file_name("Rücken") == "^rücken.json"


def test_file_name_all_upper() -> None:
    """Test file name with all uppercase letters."""
    assert get_file_name("ABBA") == "^a^b^b^a.json"


def test_file_name_lower_unicode() -> None:
    """Test file name with a lowercase letter and an umlaut."""
    assert get_file_name("über") == "über.json"


def test_file_name_upper_unicode() -> None:
    """Test file name with an uppercase letter and an umlaut."""
    assert get_file_name("Über") == "^über.json"
