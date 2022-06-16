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
