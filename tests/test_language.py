"""Test language functionality."""

from emmio.language import KnownLanguages


def test_english() -> None:
    """Check that English words are detected correctly."""

    assert KnownLanguages.ENGLISH.is_word("naïve")

    # Probably we should treat "æ" as "ae", but for now we don't allow dated
    # spellings.
    assert not KnownLanguages.ENGLISH.is_word("æsthetic")


def test_armenian() -> None:
    """Check that Armenian words are detected correctly."""

    assert KnownLanguages.ARMENIAN.is_word("հաճելի")
    assert KnownLanguages.ARMENIAN.is_word("Հաճելի")


def test_esperanto() -> None:
    """Check that Esperanto words are detected correctly."""

    assert not KnownLanguages.ESPERANTO.is_word("sweat")


def test_greek() -> None:
    """Check that Greek words are detected correctly."""

    assert KnownLanguages.MODERN_GREEK.is_word("μπόστον")
    assert KnownLanguages.MODERN_GREEK.is_word("ὀξεῖα")


def test_latin() -> None:
    """Check that Latin words are detected correctly."""

    assert KnownLanguages.LATIN.is_word("caelo")
    assert KnownLanguages.LATIN.is_word("caelō")
    assert KnownLanguages.LATIN.is_word("jus")
    assert KnownLanguages.LATIN.is_word("stylus")

    assert not KnownLanguages.LATIN.is_word("we")


def test_russian() -> None:
    """Check that Russian words are detected correctly."""

    assert KnownLanguages.RUSSIAN.is_word("пыль")
    assert KnownLanguages.RUSSIAN.is_word("сто́ящий")

    assert not KnownLanguages.RUSSIAN.is_word("чоловік")


def test_ukrainian() -> None:
    """Check that Ukrainian words are detected correctly."""

    assert KnownLanguages.UKRAINIAN.is_word("чоловік")
    assert KnownLanguages.UKRAINIAN.is_word(
        "чолові́к"
    )  # With combining acute accent.

    assert not KnownLanguages.UKRAINIAN.is_word("чоловiк")  # With ASCII "i".
    assert not KnownLanguages.UKRAINIAN.is_word("пыль")
