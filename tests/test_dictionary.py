from pathlib import Path

from emmio.dictionary.core import Dictionary, SimpleDictionary
from emmio.language import Language


def test_dictionary() -> None:

    dictionary: Dictionary = SimpleDictionary(
        "test_dictionary",
        Path("test/dictionary/test_dictionary.txt"),
        "Test Dictionary",
        {
            "livre": "book",
            "chat": "cat",
        },
        Language.from_code("fr"),
        Language.from_code("en"),
    )
