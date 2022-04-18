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


def check(text: str, links: list[str]) -> None:
    dictionary: EnglishWiktionary = EnglishWiktionary(
        Path("cache"), construct_language("eo")
    )
    parsed_links, _ = dictionary.process_definition(text)

    assert len(links) == len(parsed_links)
    for index, link in enumerate(parsed_links):
        assert link.link == links[index]


def test_1() -> None:
    check("(dated) genitive of er", ["er"])


def test_2() -> None:
    check("in the process of (followed by an infinitive clause)", [])


def test_3() -> None:
    check("past of nehmen, to take.", ["nehmen"])


def test_4() -> None:
    check(
        "third-person singular present of vermessen "
        "(“to measure, or to measure wrong”)",
        ["vermessen"],
    )


def test_5() -> None:
    check(
        "strong/mixed nominative/accusative neuter singular of letzter",
        ["letzter"],
    )


def test_uppercase() -> None:
    check("Masculine singular past participle of hacer.", ["hacer"])


def test_zh() -> None:
    check("† Alternative form of 邀 (“to invite”).", ["邀"])


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
