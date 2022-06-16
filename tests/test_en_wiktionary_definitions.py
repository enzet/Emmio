from pathlib import Path

from emmio.dictionary import Definition, DefinitionValue, Link
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.language import construct_language


dictionary: EnglishWiktionary = EnglishWiktionary(
    Path("cache"), construct_language("eo")
)


def check_parse_definition(text: str, value: tuple) -> None:
    definition: Definition = Definition(
        [DefinitionValue(x[0], "" if len(x) == 1 else x[1]) for x in value[1]],
        value[0],
    )
    assert dictionary.process_definition_2(text) == definition


def test_parse_definition_1() -> None:
    check_parse_definition("above", ([], [["above"]]))


def test_parse_definition_2() -> None:
    check_parse_definition("to stay, remain", ([], [["to stay"], ["remain"]]))


def test_parse_definition_3() -> None:
    check_parse_definition("(regional) to live", (["regional"], [["to live"]]))


def test_parse_definition_7() -> None:
    check_parse_definition("(Louisiana) diaper", (["Louisiana"], [["diaper"]]))


def test_parse_definition_4() -> None:
    check_parse_definition(
        "(colloquial) you know, like, y'know.",
        (["colloquial"], [["you know"], ["like"], ["y'know"]]),
    )
