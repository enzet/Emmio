"""Language and font specifics."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from colour import Color
from iso639 import Lang as ISO639Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DEFAULT_COLOR: Color = Color("black")

DIGRAPHS: dict[str, dict[str, str]]
with (Path(__file__).parent / "digraphs.json").open(
    encoding="utf-8"
) as config_file:
    DIGRAPHS = json.load(config_file)

LATIN_CODE: dict[str, str] = {"ā": "a", "ē": "e", "ī": "i", "ō": "o", "ū": "u"}


LanguageConfig = str
"""2-letter language code."""


@dataclass
class Language:
    """Natural language description."""

    code: str
    """2-letter language code."""

    color: Color
    """Language color."""

    symbols: str
    """All symbols allowed in the language."""

    self_name: str | None = None
    """Language name in its own language."""

    parent: Language | None = None
    """Parent language."""

    checking: Callable[[str], bool] | None = None
    """Check if the symbol is allowed in the language."""

    sentence_end: str | None = None
    """Sentence end symbol."""

    def __post_init__(self) -> None:
        self.iso639_language: ISO639Language = ISO639Language(self.code)

        self.has_symbol: Callable[[str], bool]
        if self.checking:
            self.has_symbol = self.checking
        else:
            self.has_symbol = lambda symbol: symbol in self.symbols

    @classmethod
    def from_code(cls, code: str) -> Language:
        """Get language by its code.

        :param code: ISO 639-1:2002 two-letter code
        """
        for language in KnownLanguages.get_languages():
            if code == language.get_code():
                return language

        raise LanguageNotFound(code)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Language):
            return False
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def get_name(self) -> str:
        """Get language name in English without clarifications."""
        return re.sub(" \\(.*\\)", "", self.iso639_language.name)

    def get_self_name(self) -> str:
        """Get language name in its own language."""
        if self.self_name:
            return self.self_name
        return self.get_name()

    def get_parent(self) -> Optional["Language"]:
        """Get parent language.

        E.g. Norwegian (`no`) is the parent language of Norwegian Bokmål (`nb`).
        """
        if self.parent:
            return self.parent
        return None

    def get_adjusted_color(self) -> Color:
        """Try to get adjusted color.

        If the language has a tone color, use it. Otherwise, if the language
        has a color, use it. Otherwise, use the default color.
        """
        if self.color is not None:
            color: Color = Color()
            color.set_hue(self.color.get_hue())
            color.set_saturation(0.7)
            color.set_luminance(0.4)
            return color
        if self.color is not None:
            return self.color
        return DEFAULT_COLOR

    def get_color(self) -> Color:
        """Get language color or default color if it is not set."""
        if self.color is not None:
            return self.get_adjusted_color()
        return DEFAULT_COLOR

    def get_code(self) -> str:
        """Get ISO 639-1:2002 two-letter code."""
        return self.iso639_language.pt1

    def get_part3(self) -> str:
        """Get ISO 639-3:2007 three-letter code."""
        return self.iso639_language.pt3

    def has_symbols(self) -> bool:
        """Check whether language knows its allowed symbols."""
        return self.symbols is not None

    def get_symbols(self) -> str | None:
        """Get all symbols allowed in the language."""
        return self.symbols

    def is_word(self, word: str) -> bool:
        """Check if the word is valid in the language."""
        if not self.has_symbols():
            raise ValueError(
                f"Language `{self.get_code()}` does not have symbols."
            )
        return all(self.has_symbol(c) for c in word)

    def normalize(self, word: str) -> str:
        """Get the most common form of the word.

        E.g. for Latin, the normal form of "lītera" is "litera".
        """
        return word.lower()

    def decode_text(self, text: str) -> str:
        """Decode possible digraphs."""
        if self == KnownLanguages.UKRAINIAN:
            return decode_ukrainian(text)
        if self == KnownLanguages.LATIN:
            return decode_latin(text)
        if self.get_code() in DIGRAPHS:
            digraphs = DIGRAPHS[self.get_code()]
            for digraph in digraphs:
                text = text.replace(digraph, digraphs[digraph])

        return text

    def __repr__(self) -> str:
        return self.get_code()

    def get_random_color(self) -> str:
        """Get random color for the language."""
        return "#" + str(hex(abs(hash(self.get_code()))))[2:8]

    def get_variant(self, word: str) -> str | None:
        """Get another way to write the word."""

        if self == KnownLanguages.LATIN:
            decoded = self.decode_text(word)
            if decoded != word:
                return decoded
        if self == KnownLanguages.GERMAN and word[0].upper() != word[0]:
            return word[0].upper() + word[1:]

        return None


def letter_range(start: str, stop: str) -> str:
    """Get range of letters from Unicode code point."""
    return "".join(chr(x) for x in range(ord(start), ord(stop) + 1))


KATAKANA: str = letter_range("゠", "ヿ")
HIRAGANA: str = letter_range("ぁ", "ゟ")
KANJI: str = (
    letter_range("㐀", "䶵")
    + letter_range("一", "鿋")
    + letter_range("豈", "頻")
)
ARABIC_LETTERS: str = letter_range("\u0620", "\u06FF")  # FIXME: check.
KOREAN_LETTERS: str = letter_range("\u1100", "\u11FF") + letter_range(
    "\uAC00", "\uD7A3"
)
JAPANESE_LETTERS: str = KATAKANA + HIRAGANA + KANJI
ARMENIAN_LETTERS: str = letter_range("\u0561", "\u0587") + letter_range(
    "\u0531", "\u0556"
)

LATIN_UPPER: str = letter_range("A", "Z")
LATIN_LETTERS: str = LATIN_UPPER + LATIN_UPPER.lower()

RU_UPPER: str = letter_range("А", "Я") + "Ё"
UK_UPPER: str = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
EO_UPPER: str = "ABCĈDEFGĜHĤIJĴKLMNOPRSŜTUŬVZ"

SKIPPERS: str = "'’"

LATIN_LIGATURES: dict[str, str] = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬆ": "st",
    "ﬅ": "ft",
}


class KnownLanguages:
    """Languages supported by the application."""

    @classmethod
    def get_languages(cls) -> list[Language]:
        """Return all fields of the class."""
        return [
            value
            for value in cls.__dict__.values()
            if isinstance(value, Language)
        ]

    ARABIC: Language = Language(
        "ar",
        Color("#286035"),  # Green color of the Arab League flag.
        ARABIC_LETTERS,
    )
    ARMENIAN: Language = Language(
        "hy",
        Color("#E8AD3B"),  # Orange color of the Armenian flag.
        ARMENIAN_LETTERS,
        checking=lambda symbol: "\u0561" <= symbol <= "\u0587"
        or "\u0531" <= symbol <= "\u0556",
        self_name="հայերեն",
    )
    CHINESE: Language = Language(
        "zh",
        Color("#DB352F"),  # Red color of the Chinese flag.
        KANJI,
        self_name="中文",
    )
    ENGLISH: Language = Language(
        "en",
        Color("#071B65"),  # Blue color of the United Kingdom flag.
        LATIN_LETTERS + "ÏïÉé" + "".join(LATIN_LIGATURES.keys()),
    )
    ESPERANTO: Language = Language(
        "eo",
        Color("#44982A"),  # Green color of the Esperanto flag.
        EO_UPPER.lower() + EO_UPPER,
    )
    FRENCH: Language = Language(
        "fr",
        Color("#4193C3"),  # Blue color of the Francophonie flag.
        LATIN_LETTERS
        + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœ"
        + "".join(LATIN_LIGATURES.keys())
        + SKIPPERS,
        self_name="français",
    )
    GERMAN: Language = Language(
        "de",
        Color("#F7D046"),  # Yellow color of the German flag.
        LATIN_LETTERS + "ÄäÖöÜüß",
        self_name="deutsch",
    )
    GEORGIAN: Language = Language(
        "ka",
        Color("#EA3323"),  # Red color of the Georgian flag.
        "აბგდევზთიკლმნოპჟრსტუფქღყშჩცძწჭხჯჰ" + "ჱჲჳჴჵ",
        self_name="ქართული",
    )
    HEBREW: Language = Language(
        "he",
        Color("#1334B2"),  # Blue color of the Israel flag.
        letter_range("\u0590", "\u05F4"),
        self_name="עִברִית",
    )
    ICELANDIC: Language = Language(
        "is",
        Color("#205098"),  # Blue color of the Iceland flag.
        "AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖaábdðeéfghiíjklmnoóprstuúvxyýþæö",
        self_name="íslenska",
    )
    ITALIAN: Language = Language(
        "it",
        Color("#41914D"),  # Green color of the Italy flag.
        LATIN_LETTERS,
        self_name="italiano",
    )
    JAPANESE: Language = Language(
        "ja",
        Color("#AE232F"),  # Red color of the Japan flag.
        JAPANESE_LETTERS,
        self_name="日本語",
    )
    KOREAN: Language = Language(
        "ko",
        Color("#1B449C"),  # Blue color of the South Korea flag.
        KOREAN_LETTERS,
        self_name="한국어",
    )
    LATIN: Language = Language(
        "la",
        Color("#FDF351"),  # Yellow color of the Vatican flag.
        LATIN_LETTERS + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
        self_name="latīna",
    )
    MODERN_GREEK: Language = Language(
        "el",
        Color("#2A5DA9"),  # Blue color of the Greece flag.
        "ΑαΒβΓγΔδΕεΖζΗηΘθΙιΚκΛλΜμΝνΞξΟοΠπΡρΣσςΤτΥυΦφΧχΨψΩω",
        self_name="ελληνικά",
    )
    NORWEGIAN: Language = Language(
        "no",
        Color("#061A57"),  # Blue color of the Norway flag.
        LATIN_LETTERS + "ÆØÅæøå",
        self_name="norsk",
    )
    NORWEGIAN_BOKMAL: Language = Language(
        "nb",
        Color("#061A57"),  # Blue color of the Norway flag.
        LATIN_LETTERS + "ÆØÅæøå",
        self_name="norsk bokmål",
        parent=NORWEGIAN,
    )
    PORTUGUESE: Language = Language(
        "pt",
        Color("#2B6519"),  # Green color of the Portugal flag.
        LATIN_LETTERS + "ÁÂÃ̃ÀÇÉÊÍÓÔÕÚáâã̃àçéêíóôõú",
        self_name="português",
    )
    POLISH: Language = Language(
        "pl",
        Color("#CB2E3F"),  # Red color of the Poland flag.
        "AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŹŻaąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż",
        self_name="polski",
    )
    RUSSIAN: Language = Language(
        "ru",
        Color("#1335A1"),  # Blue color of the Russia flag.
        RU_UPPER + RU_UPPER.lower(),
        self_name="русский",
    )
    SPANISH: Language = Language(
        "es",
        Color("#F6C844"),  # Yellow color of the Spain flag.
        LATIN_LETTERS + "ÑÁÉÍÓÚÜñáéíóúü",
        self_name="español",
    )
    SWEDISH: Language = Language(
        "sv",
        Color("#205090"),  # Blue color of the Sweden flag.
        LATIN_LETTERS + "ÅÄÖåäö",
        self_name="svenska",
    )
    UKRAINIAN: Language = Language(
        "uk",
        Color("#F9D849"),  # Yellow color of the Ukrainian flag.
        UK_UPPER.lower() + UK_UPPER + SKIPPERS,
        self_name="українська",
    )


def decode_ukrainian(text: str) -> str:
    """Decode text in Ukrainian.

    Merely replace ASCII "i" symbol with Unicode U+0456.
    """
    return text.replace("i", "і")


def decode_latin(text: str) -> str:
    """Remove diacritics from Latin text."""
    for symbol, replacement in LATIN_CODE.items():
        text = text.replace(symbol, replacement)
    return text


@dataclass
class LanguageNotFound(ValueError):
    """Language with the given code was not found."""

    code: str
    """ISO 639-1:2002 two-letter code."""
