from pathlib import Path

from emmio.dictionary.en_wiktionary import get_file_name


def test_file_name_lower() -> None:
    assert get_file_name("rücken") == "rücken.json"


def test_file_name_upper() -> None:
    assert get_file_name("Rücken") == "^rücken.json"


def test_file_name_all_upper() -> None:
    assert get_file_name("ABBA") == "^a^b^b^a.json"


def test_file_name_lower_unicode() -> None:
    assert get_file_name("über") == "über.json"


def test_file_name_upper_unicode() -> None:
    assert get_file_name("Über") == "^über.json"
