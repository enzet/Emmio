import pytest

from emmio.language import ENGLISH, FRENCH
from emmio.sentence.core import split_sentence


def test_word():
    assert split_sentence("Word", ENGLISH) == [("Word", "word")]


def test_word_and_symbol():
    assert split_sentence("Word.", ENGLISH) == [
        ("Word", "word"),
        (".", "symbol"),
    ]


@pytest.mark.skip(reason="Fix apostrophe splitting.")
def test_en_apostrophe():
    assert split_sentence("don't", ENGLISH) == [("don't", "word")]


def test_fr():
    assert split_sentence("n'importe quel", FRENCH) == [
        ("n'importe", "word"),
        (" ", "symbol"),
        ("quel", "word"),
    ]


def test_hy():
    """խոսե՞լ։"""
