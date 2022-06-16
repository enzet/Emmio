from pathlib import Path

from emmio.dictionary import Definition, DefinitionValue, Link
from emmio.external.en_wiktionary import EnglishWiktionary
from emmio.language import construct_language


dictionary: EnglishWiktionary = EnglishWiktionary(
    Path("cache"), construct_language("eo")
)


def check_form(text: str, value: tuple) -> None:
    definition: Definition = Definition(
        [DefinitionValue(x[0], "" if len(x) == 1 else x[1]) for x in value[1]],
        value[0],
    )
    assert dictionary.process_definition_2(text) == definition


def check_link(text: str, link_type: str, link_value: str) -> None:
    assert dictionary.process_definition_2(text) == Link(link_type, link_value)


def test_definition() -> None:
    check_form("above", ([], [["above"]]))


def test_definition_separated_by_comma() -> None:
    check_form("to stay, remain", ([], [["to stay"], ["remain"]]))


def test_definition_separated_by_colon() -> None:
    check_form("lecture; talk", ([], [["lecture"], ["talk"]]))


def test_definition_with_descriptor() -> None:
    check_form("(regional) to live", (["regional"], [["to live"]]))


def test_definition_with_place_descriptor() -> None:
    check_form("(Louisiana) diaper", (["Louisiana"], [["diaper"]]))


def test_separated_definitions_with_descriptor() -> None:
    check_form(
        "(colloquial) you know, like, y'know.",
        (["colloquial"], [["you know"], ["like"], ["y'know"]]),
    )


def test_link() -> None:
    check_link("plural of média", "plural", "média")
