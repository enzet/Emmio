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
        ("n", SentenceElement.WORD),
        ("'", SentenceElement.SYMBOL),
        ("importe", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("quel", SentenceElement.WORD),
    ]


def test_italian_accented_letters() -> None:
    """Test that accented letters are parts of Italian words."""

    assert split_sentence("Perché è così?", KnownLanguages.ITALIAN) == [
        ("Perché", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("è", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("così", SentenceElement.WORD),
        ("?", SentenceElement.SYMBOL),
    ]


def test_italian_borrowed_letters() -> None:
    """Test that borrowed letters are parts of Italian words."""

    assert split_sentence("Il weekend è bello.", KnownLanguages.ITALIAN) == [
        ("Il", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("weekend", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("è", SentenceElement.WORD),
        (" ", SentenceElement.SYMBOL),
        ("bello", SentenceElement.WORD),
        (".", SentenceElement.SYMBOL),
    ]


def test_italian_native_word() -> None:
    """Test native and borrowed Italian words."""

    assert KnownLanguages.ITALIAN.is_word("perché")
    assert KnownLanguages.ITALIAN.is_native_word("perché")
    assert KnownLanguages.ITALIAN.is_word("weekend")
    assert not KnownLanguages.ITALIAN.is_native_word("weekend")
    assert not KnownLanguages.ITALIAN.is_word("señor")


def test_native_and_borrowed_words() -> None:
    """Test native and borrowed words in different languages."""

    for language, native, borrowed in (
        (KnownLanguages.ENGLISH, "naive", "naïve"),
        (KnownLanguages.FRENCH, "château", "kilo"),
        (KnownLanguages.GERMAN, "quer", "Yacht"),
        (KnownLanguages.NORWEGIAN, "kjærlighet", "quiz"),
        (KnownLanguages.PORTUGUESE, "coração", "yoga"),
        (KnownLanguages.POLISH, "żółty", "quiz"),
        (KnownLanguages.SPANISH, "niño", "kiwi"),
        (KnownLanguages.SWEDISH, "kärlek", "webb"),
        (KnownLanguages.CZECH, "čtvrtek", "xylofon"),
        (KnownLanguages.DUTCH, "vrij", "baby"),
        (KnownLanguages.TURKISH, "güzel", "taxi"),
        (KnownLanguages.VIETNAMESE, "người", "jazz"),
    ):
        assert language.is_word(native), (language, native)
        assert language.is_native_word(native), (language, native)
        assert language.is_word(borrowed), (language, borrowed)
        assert not language.is_native_word(borrowed), (language, borrowed)


def test_foreign_letter_does_not_split_word() -> None:
    """Test that a letter outside the language alphabet does not split a word.

    "Señor" in an Italian sentence should not be split into words "Se" and
    "or", otherwise a search for these words would wrongly match the sentence.
    """

    assert split_sentence("Sì, señor!", KnownLanguages.ITALIAN) == [
        ("Sì", SentenceElement.WORD),
        (",", SentenceElement.SYMBOL),
        (" ", SentenceElement.SYMBOL),
        ("señor", SentenceElement.SYMBOL),
        ("!", SentenceElement.SYMBOL),
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

    check_normalize(
        KnownLanguages.ARMENIAN, [("Խոսե՞լ", "խոսել"), ("Խաղա՛", "խաղա")]
    )


def test_latin_normalize() -> None:
    """Test normalizing Latin words."""

    check_normalize(
        KnownLanguages.LATIN, [("formulæ", "formulae"), ("lītera", "litera")]
    )


def test_russian_normalize() -> None:
    """Test normalizing Russian words."""
    check_normalize(KnownLanguages.RUSSIAN, [("ко́шка", "кошка")])
