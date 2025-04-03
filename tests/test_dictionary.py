"""Test for dictionary."""

from pathlib import Path

from emmio.dictionary.core import SimpleDictionary
from emmio.language import KnownLanguages


def test_dictionary() -> None:
    """Test simple dictionary creation."""

    SimpleDictionary(
        "test_dictionary",
        Path("test/dictionary/test_dictionary.txt"),
        "Test Dictionary",
        {"livre": "book", "chat": "cat"},
        KnownLanguages.FRENCH,
        KnownLanguages.ENGLISH,
    )
