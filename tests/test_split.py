"""Test for sentence splitting."""

import pytest

from emmio.language import ENGLISH, FRENCH
from emmio.sentence.core import SentenceElement, split_sentence


def test_word():
    assert split_sentence("Word", ENGLISH) == [("Word", SentenceElement.WORD)]


def test_word_and_symbol():
    assert split_sentence("Word.", ENGLISH) == [
        ("Word", SentenceElement.WORD),
        (".", SentenceElement.SYMBOL),
    ]


@pytest.mark.skip(reason="Fix apostrophe splitting.")
def test_en_apostrophe():
    assert split_sentence("don't", ENGLISH) == [("don't", SentenceElement.WORD)]


def test_fr():
    assert split_sentence("n'importe quel", FRENCH) == [
        ("n'importe", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("quel", SentenceElement.WORD),
    ]


def test_hy():
    """խոսե՞լ։"""
