from pathlib import Path

from emmio.dictionary import Link
from emmio.external.en_wiktionary import EnglishWiktionary, get_file_name
from emmio.language import construct_language


def test_process_definition() -> None:
    dictionary: EnglishWiktionary = EnglishWiktionary(
        Path("cache"), construct_language("eo")
    )
    links, text = dictionary.process_definition("A single act of teasing")
    assert not links
    assert text == "A single act of teasing"


def test_process_definition2() -> None:
    dictionary: EnglishWiktionary = EnglishWiktionary(
        Path("cache"), construct_language("eo")
    )
    links, text = dictionary.process_definition("present participle of tease")
    assert len(links) == 1
    assert links[0] == Link("present participle", "tease")
    assert text == "present participle of tease"
