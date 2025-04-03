"""Test language functionality."""

import pytest

from emmio.language import KnownLanguages


def test_english() -> None:
    """Check that English words are detected correctly."""

    assert KnownLanguages.ENGLISH.is_word("naïve")

    # Probably we should treat "æ" as "ae", but for now we don't allow dated
    # spellings.
    assert not KnownLanguages.ENGLISH.is_word("æsthetic")


def test_esperanto() -> None:
    """Check that Esperanto words are detected correctly."""

    assert not KnownLanguages.ESPERANTO.is_word("sweat")


def test_russian() -> None:
    """Check that Russian words are detected correctly."""

    assert KnownLanguages.RUSSIAN.is_word("пыль")
    assert not KnownLanguages.RUSSIAN.is_word("чоловік")


@pytest.mark.skip(reason="Fix accent marks detection.")
def test_ukrainian() -> None:
    """Check that Ukrainian words are detected correctly."""

    assert KnownLanguages.UKRAINIAN.is_word("чоловік")
    assert KnownLanguages.UKRAINIAN.is_word(
        "чолові́к"
    )  # With combining acute accent.

    assert not KnownLanguages.UKRAINIAN.is_word("чоловiк")  # With ASCII "i".
    assert not KnownLanguages.UKRAINIAN.is_word("пыль")
