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


def test_esperanto_encode_texts() -> None:
    """Check simplified spellings that decode back to the word."""

    esperanto = KnownLanguages.ESPERANTO

    assert esperanto.encode_texts("anstataŭ") == ["anstataux", "anstatauh"]
    assert esperanto.encode_texts("ĉiuĵaŭde") == ["cxiujxauxde", "chiujhauhde"]
    assert esperanto.encode_texts("domo") == []

    for variant in esperanto.encode_texts("ŝanĝi"):
        assert esperanto.decode_text(variant) == "ŝanĝi"


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


def test_hebrew() -> None:
    """Check that Hebrew words are detected correctly."""

    assert KnownLanguages.HEBREW.is_word("דרלה")  # Proper noun "Darla".
    assert KnownLanguages.HEBREW.is_word("על-ידי")


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


def test_turkish() -> None:
    """Check that Turkish words are detected correctly."""

    assert KnownLanguages.TURKISH.is_word("köşe")
    assert KnownLanguages.TURKISH.is_word("ışık")  # With dotless letters.

    assert not KnownLanguages.TURKISH.is_word("книга")


def test_extra_symbols() -> None:
    """Check letters reported as missing from a basic keyboard."""

    assert KnownLanguages.SPANISH.get_extra_symbols() == "ñáéíóúü"
    assert KnownLanguages.GERMAN.get_extra_symbols() == "äöüß"
    assert KnownLanguages.UKRAINIAN.get_extra_symbols() == "ґєії'’"

    # Plain Latin and Russian alphabets are assumed to be on the keyboard.
    assert KnownLanguages.ENGLISH.get_extra_symbols() == ""
    assert KnownLanguages.RUSSIAN.get_extra_symbols() == ""

    # Caseless scripts need a whole layout, not a row of buttons.
    assert KnownLanguages.JAPANESE.get_extra_symbols() == ""
    assert KnownLanguages.HEBREW.get_extra_symbols() == ""

    # Too many missing letters for buttons: a best-effort Unicode-block
    # alphabet and the heavily diacritised Vietnamese.
    assert KnownLanguages.BULGARIAN.get_extra_symbols() == ""
    assert KnownLanguages.VIETNAMESE.get_extra_symbols() == ""


def test_thai() -> None:
    """Check that Thai words are detected correctly."""

    assert KnownLanguages.THAI.is_word("สวัสดี")

    assert not KnownLanguages.THAI.is_word("hello")


def test_hindi() -> None:
    """Check that Hindi words are detected correctly."""

    assert KnownLanguages.HINDI.is_word("नमस्ते")

    assert not KnownLanguages.HINDI.is_word("hello")
