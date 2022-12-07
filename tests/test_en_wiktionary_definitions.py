from pathlib import Path

from emmio.dictionary.core import Definition, DefinitionValue, Link
from emmio.dictionary.en_wiktionary import EnglishWiktionary
from emmio.language import construct_language


DICTIONARY: EnglishWiktionary = EnglishWiktionary(
    Path("cache"), construct_language("eo")
)


def check_form(text: str, value: tuple) -> None:
    """Check whether the form parsing is valid."""
    definition: Definition = Definition(
        [DefinitionValue(x[0], "" if len(x) == 1 else x[1]) for x in value[1]],
        value[0],
    )
    assert DICTIONARY.process_definition(text) == definition


def check_link(text: str, link_type: str, link_value: str) -> None:
    """Check whether the link parsing is valid."""
    assert DICTIONARY.process_definition(text) == Link(link_type, link_value)


def test_link_with_dot() -> None:
    check_link("past of nehmen, to take.", "past", "nehmen")


def test_link_with_dot_2() -> None:
    check_link(
        "Masculine singular past participle of hacer.",
        "Masculine singular past participle",
        "hacer",
    )


def test_link_with_parentheses() -> None:
    check_link(
        "third-person singular present of vermessen "
        "(“to measure, or to measure wrong”)",
        "third-person singular present",
        "vermessen",
    )


def test_link_with_slash() -> None:
    check_link(
        "second/third-person singular present of lassen",
        "second/third-person singular present",
        "lassen",
    )


def test_link_with_slashes() -> None:
    check_link(
        "strong/mixed nominative/accusative neuter singular of letzter",
        "strong/mixed nominative/accusative neuter singular",
        "letzter",
    )


def test_link_with_colon() -> None:
    check_link(
        "comparative form of tough: more tough",
        "comparative form",
        "tough",
    )


def test_japanese_link():
    check_link(
        "† Alternative form of 邀 (“to invite”).", "† Alternative form", "邀"
    )


def test_spanish_links() -> None:
    check_link(
        "Formal  second-person singular   (usted)  present indicative  form "
        "of formar.",
        "Formal  second-person singular   (usted)  present indicative  form",
        "formar",
    )
    check_link(
        "Informal second-person singular (t\u00fa) affirmative imperative form "
        "of formar.",
        "Informal second-person singular (t\u00fa) affirmative imperative form",
        "formar",
    )
    check_link(
        "Third-person singular   (\u00e9l, ella, also used with usted?)  "
        "present indicative  form of formar.",
        "Third-person singular   (\u00e9l, ella, also used with usted?)  "
        "present indicative  form",
        "formar",
    )


def test_definition() -> None:
    """Test simple definition."""
    check_form("above", ([], [["above"]]))


def test_form_with_parentheses() -> None:
    check_form(
        "in the process of (followed by an infinitive clause)",
        ([], [["in the process of", "followed by an infinitive clause"]]),
    )


def test_definition_separated_by_comma() -> None:
    """Test definitions, separated by comma."""
    check_form("to stay, remain", ([], [["to stay"], ["remain"]]))


def test_definition_separated_by_colon() -> None:
    """Test definitions, separated by colon."""
    check_form("lecture; talk", ([], [["lecture"], ["talk"]]))


def test_definition_with_descriptor() -> None:
    """Test definitions with one descriptor."""
    check_form("(regional) to live", (["regional"], [["to live"]]))


def test_definition_with_place_descriptor() -> None:
    """Test definitions with regional descriptor."""
    check_form("(Louisiana) diaper", (["Louisiana"], [["diaper"]]))


def test_separated_definitions_with_descriptor() -> None:
    """Test definitions with descriptor, separated by comma."""
    check_form(
        "(colloquial) you know, like, y'know.",
        (["colloquial"], [["you know"], ["like"], ["y'know"]]),
    )


def test_definition_with_double_parentheses() -> None:
    check_form(
        "(intransitive) to insist (auf (\u201con\u201d))",
        (["intransitive"], [["to insist", "auf (\u201con\u201d)"]]),
    )


def test_link() -> None:
    """Test link."""
    check_link("plural of média", "plural", "média")


def test_link_with_description() -> None:
    """Test link with simple description before."""
    check_link("(dated) genitive of er", "genitive", "er")
