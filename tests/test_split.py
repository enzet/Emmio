"""Test for sentence splitting."""

import pytest

from emmio.language import KnownLanguages, Language
from emmio.sentence.core import SentenceElement, split_sentence


def test_word() -> None:
    """Test English sentence splitting with word."""
    assert split_sentence("Word", KnownLanguages.ENGLISH) == [
        ("Word", SentenceElement.WORD)
    ]


def test_word_and_symbol() -> None:
    """Test English sentence splitting with word and symbol."""
    assert split_sentence("Word.", KnownLanguages.ENGLISH) == [
        ("Word", SentenceElement.WORD),
        (".", SentenceElement.SYMBOL),
    ]


@pytest.mark.skip(reason="Fix apostrophe splitting.")
def test_en_apostrophe() -> None:
    """Test English sentence splitting with apostrophe."""

    assert split_sentence("don't", KnownLanguages.ENGLISH) == [
        ("don't", SentenceElement.WORD)
    ]


def test_french() -> None:
    """Test French sentence splitting."""

    assert split_sentence("n'importe quel", KnownLanguages.FRENCH) == [
        ("n'importe", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("quel", SentenceElement.WORD),
    ]


def test_armenian() -> None:
    """Test Armenian sentence splitting."""

    assert split_sentence("Խոսե՞լ։", KnownLanguages.ARMENIAN) == [
        ("Խոսե՞լ", SentenceElement.WORD),
        ("։", SentenceElement.SYMBOL),
    ]
    assert split_sentence("Խաղա՛ հետս:", KnownLanguages.ARMENIAN) == [
        ("Խաղա՛", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("հետս", SentenceElement.WORD),
        (":", SentenceElement.SYMBOL),
    ]


def check_normalize(language: Language, pairs: list[tuple[str, str]]) -> None:
    """Check normalizing Armenian words."""

    for original, normalized in pairs:
        assert language.normalize(original) == normalized


def test_armenian_normalize() -> None:
    """Test normalizing Armenian words."""

    check_normalize(KnownLanguages.ARMENIAN, [("Խոսե՞լ", "խոսել")])
