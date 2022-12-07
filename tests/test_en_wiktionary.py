from pathlib import Path

from emmio.dictionary.core import Link, Definition
from emmio.dictionary.en_wiktionary import EnglishWiktionary, get_file_name
from emmio.language import construct_language


def test_process_definition() -> None:
    dictionary: EnglishWiktionary = EnglishWiktionary(
        Path("cache"), construct_language("eo")
    )
    definition: Definition = dictionary.process_definition(
        "A single act of teasing"
    )
    assert definition.values[0].value == "A single act of teasing"


def test_process_definition2() -> None:
    dictionary: EnglishWiktionary = EnglishWiktionary(
        Path("cache"), construct_language("eo")
    )
    link: Link = dictionary.process_definition("present participle of tease")
    assert link == Link("present participle", "tease")


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
