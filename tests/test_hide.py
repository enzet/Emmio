"""Test for hiding words in text."""

import pytest

from emmio.text_util import sanitize


def check(sentence: str, hidden: str, words_to_hide: list[str]) -> None:
    """Check the sanitization of a sentence.

    :param sentence: sentence to sanitize
    :param hidden: sentence with underscores instead of the words to hide
    :param words_to_hide: words that should be replaced with underscores
    """
    assert sanitize(sentence, words_to_hide, "_") == hidden


def test_word() -> None:
    """Test sanitizing one word from a sentence."""
    check("I want an apple.", "I want an _____.", ["apple"])


def test_two_words() -> None:
    """Test sanitizing two words from a sentence."""
    check(
        "I want an apple, and he wants an apple.",
        "I want an _____, and he wants an _____.",
        ["apple"],
    )


def test_uppercase() -> None:
    """Test sanitizing a word with different case from a sentence."""
    check("I want an Apple.", "I want an _____.", ["apple"])


def test_russian_end_accent() -> None:
    """Test sanitizing a Russian word with a diacritic symbol at the end.

    In Russian accent is an additional diacritic symbol, which is not the part
    of the word.
    """
    check("зима́ – холодное время года", "____ – холодное время года", ["зима"])


def test_russian_middle_accent() -> None:
    """Test sanitizing a Russian word with a diacritic symbol in the end."""
    check("ма́рт – третий месяц", "____ – третий месяц", ["март"])


def test_ukrainian_accent() -> None:
    """Test sanitizing a Ukrainian word with a diacritic symbol.

    In Ukrainian accent is an additional diacritic symbol, which is not the part
    of the word.
    """
    check("яки́й", "____", ["який"])


@pytest.mark.skip(reason="Not implemented yet.")
def test_francais() -> None:
    """Test sanitizing a French word with an acute."""
    check("reward; recompense", "reward; __________", ["récompense"])
