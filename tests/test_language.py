"""Test language functionality."""

import pytest

from emmio.language import ENGLISH, ESPERANTO, RUSSIAN, UKRAINIAN


def test_english() -> None:
    """Check that English words are detected correctly."""

    assert ENGLISH.is_word("naïve")

    # Probably we should treat "æ" as "ae", but for now we don't allow dated
    # spellings.
    assert not ENGLISH.is_word("æsthetic")


def test_esperanto() -> None:
    """Check that Esperanto words are detected correctly."""

    assert not ESPERANTO.is_word("sweat")


def test_russian() -> None:
    """Check that Russian words are detected correctly."""

    assert RUSSIAN.is_word("пыль")
    assert not RUSSIAN.is_word("чоловік")


@pytest.mark.skip(reason="Fix accent marks detection.")
def test_ukrainian() -> None:
    """Check that Ukrainian words are detected correctly."""

    assert UKRAINIAN.is_word("чоловік")
    assert UKRAINIAN.is_word("чолові́к")  # With combining acute accent.

    assert not UKRAINIAN.is_word("чоловiк")  # With ASCII "i".
    assert not UKRAINIAN.is_word("пыль")
