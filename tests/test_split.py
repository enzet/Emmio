"""Test for sentence splitting."""

import pytest

from emmio.language import ENGLISH, FRENCH
from emmio.sentence.core import SentenceElement, split_sentence


def test_word() -> None:
    """Test English sentence splitting with word."""
    assert split_sentence("Word", ENGLISH) == [("Word", SentenceElement.WORD)]


def test_word_and_symbol() -> None:
    """Test English sentence splitting with word and symbol."""
    assert split_sentence("Word.", ENGLISH) == [
        ("Word", SentenceElement.WORD),
        (".", SentenceElement.SYMBOL),
    ]


@pytest.mark.skip(reason="Fix apostrophe splitting.")
def test_en_apostrophe() -> None:
    """Test English sentence splitting with apostrophe."""
    assert split_sentence("don't", ENGLISH) == [("don't", SentenceElement.WORD)]


def test_french() -> None:
    """Test French sentence splitting."""

    assert split_sentence("n'importe quel", FRENCH) == [
        ("n'importe", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("quel", SentenceElement.WORD),
    ]


def test_armenian() -> None:
    """խոսե՞լ։"""
