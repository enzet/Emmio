"""Language and font specifics."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from colour import Color
from iso639 import Lang as ISO639Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DEFAULT_COLOR: Color = Color("black")

DIGRAPHS: dict[str, dict[str, str]]
with (Path(__file__).parent / "digraphs.json").open() as config_file:
    DIGRAPHS = json.load(config_file)


LATIN_CODE: dict[str, str] = {
    "ā": "a",
    "ē": "e",
    "ī": "i",
    "ō": "o",
    "ū": "u",
}


LanguageConfig = str


class Language:
    """Natural language description."""

    def __init__(
        self,
        code: str,
        color: Color,
        symbols: str = None,
        self_name: str = None,
        tone: Color | None = None,
        checking: Optional[Callable] = None,
        sentence_end: str | None = None,
    ) -> None:
        self.code: str = code
        self.symbols: str = symbols
        self.color: Color | None = color
        self.self_name: str = self_name
        self.tone: Color | None = tone
        self.sentence_end: str | None = sentence_end
        self.iso639_language = ISO639Language(code)

        if checking:
            self.has_symbol = checking
        else:
            self.has_symbol = lambda x: x in self.symbols

    @classmethod
    def from_code(cls, code: str):
        for language in KNOWN_LANGUAGES:
            if code == language.get_code():
                return language

        raise LanguageNotFound(code)

    def __eq__(self, other: "Language") -> bool:
        assert isinstance(other, Language)
        return self.code == other.code

    def __hash__(self) -> int:
        return hash(self.code)

    def get_name(self) -> str:
        return re.sub(" \\(.*\\)", "", self.iso639_language.name)

    def get_self_name(self) -> str:
        if self.self_name:
            return self.self_name
        return self.get_name()

    def get_adjusted_color(self) -> Color:
        if self.tone is not None:
            c = Color()
            c.set_hue(self.tone.get_hue())
            c.set_saturation(0.5)
            c.set_luminance(0.4)
            return c
        if self.color is not None:
            return self.color
        return DEFAULT_COLOR

    def get_color(self) -> Color:
        if self.color is not None:
            return self.color
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

    def decode_text(self, text: str) -> str:
        """Decode possible digraphs."""
        if self == UKRAINIAN:
            return decode_ukrainian(text)
        if self == LATIN:
            return decode_latin(text)
        if self.get_code() in DIGRAPHS:
            digraphs = DIGRAPHS[self.get_code()]
            for digraph in digraphs:
                text = text.replace(digraph, digraphs[digraph])

        return text

    def __repr__(self) -> str:
        return self.get_code()

    def get_random_color(self) -> str:
        return "#" + str(hex(abs(hash(self.get_code()))))[2:8]

    def get_variant(self, word: str) -> str | None:
        """Get another way to write the word."""
        if self == LATIN:
            decoded = self.decode_text(word)
            if decoded != word:
                return decoded
        if self == GERMAN and word[0].upper() != word[0]:
            return word[0].upper() + word[1:]

        return None


def letter_range(start: str, stop: str) -> str:
    return "".join(chr(x) for x in range(ord(start), ord(stop) + 1))


KATAKANA: str = letter_range("゠", "ヿ")
HIRAGANA: str = letter_range("ぁ", "ゟ")
KANJI: str = (
    letter_range("㐀", "䶵")
    + letter_range("一", "鿋")
    + letter_range("豈", "頻")
)
ARABIC_LETTERS: str = letter_range("\u0620", "\u06FF")  # FIXME: check.
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

ARABIC: Language = Language("ar", Color("#FF8800"), ARABIC_LETTERS)
KOREAN_LETTERS: str = letter_range("\u1100", "\u11FF") + letter_range(
    "\uAC00", "\uD7A3"
)
ARMENIAN: Language = Language(
    "hy",
    Color("#888800"),
    ARMENIAN_LETTERS,
    tone=Color("#888800"),
    checking=lambda x: "\u0561" <= x <= "\u0587" or "\u0531" <= x <= "\u0556",
    self_name="հայերեն",
)
CHINESE: Language = Language("zh", Color("#444400"), KANJI, self_name="中文")
ENGLISH: Language = Language(
    "en",
    Color("#2F2FC5"),
    LATIN_LETTERS + "ÏïÉé" + "".join(LATIN_LIGATURES.keys()),
    tone=Color("#0B2065"),
)
ESPERANTO: Language = Language(
    "eo",
    Color("#009900"),
    EO_UPPER.lower() + EO_UPPER,
    tone=Color("#43972A"),
)
FRENCH: Language = Language(
    "fr",
    Color("#4DA9CC"),  # #16ACEC
    LATIN_LETTERS
    + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœ"
    + "".join(LATIN_LIGATURES.keys())
    + SKIPPERS,
    tone=Color("#4192C1"),
    self_name="français",
)
GERMAN: Language = Language(
    "de",
    Color("#C3A656"),
    LATIN_LETTERS + "ÄäÖöÜüß",
    self_name="deutsch",
    tone=Color("#F7D046"),
)  # #FED12E
ICELANDIC: Language = Language(
    "is",
    Color("#008844"),
    "AÁBDÐEÉFGHIÍJKLMNOÓPRSTUÚVXYÝÞÆÖaábdðeéfghiíjklmnoóprstuúvxyýþæö",
    self_name="íslenska",
)
ITALIAN: Language = Language(
    "it", Color("#008888"), LATIN_LETTERS, self_name="italiano"
)
JAPANESE: Language = Language(
    "ja", Color("#CC2200"), JAPANESE_LETTERS, self_name="日本語"
)
KOREAN: Language = Language("ko", Color("#880088"), self_name="한국어")
LATIN: Language = Language(
    "la",
    Color("#666666"),
    LATIN_LETTERS + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
    self_name="latīna",
)
MODERN_GREEK: Language = Language(
    "el",
    Color("#444444"),
    "ΑαΒβΓγΔδΕεΖζΗηΘθΙιΚκΛλΜμΝνΞξΟοΠπΡρΣσςΤτΥυΦφΧχΨψΩω",
    self_name="ελληνικά",
)
PORTUGUESE: Language = Language(
    "pt",
    Color("#00AA00"),
    LATIN_LETTERS + "ÁÂÃ̃ÀÇÉÊÍÓÔÕÚáâã̃àçéêíóôõú",
    self_name="português",
)
POLISH: Language = Language(
    "pl",
    Color("#00AA00"),
    "AĄBCĆDEĘFGHIJKLŁMNŃOÓPQRSŚTUVWXYZŹŻaąbcćdeęfghijklłmnńoópqrsśtuvwxyzźż",
    self_name="polski",
)
RUSSIAN: Language = Language(
    "ru", Color("#AAAAAA"), RU_UPPER + RU_UPPER.lower(), self_name="русский"
)
SPANISH: Language = Language(
    "es",
    Color("#CB3636"),  # "C61323"
    LATIN_LETTERS + "ÑÁÉÍÓÚÜñáéíóúü",
    self_name="español",
    tone=Color("#9E2823"),
)
SWEDISH: Language = Language(
    "sv", Color("#004488"), LATIN_LETTERS + "ÅÄÖåäö", self_name="svenska"
)
UKRAINIAN: Language = Language(
    "uk",
    Color("#E5D144"),
    UK_UPPER.lower() + UK_UPPER + SKIPPERS,
    self_name="українська",
    tone=Color("#F8D648"),
)

KNOWN_LANGUAGES: set[Language] = {
    ARABIC,
    ARMENIAN,
    CHINESE,
    ENGLISH,
    ESPERANTO,
    FRENCH,
    GERMAN,
    ICELANDIC,
    ITALIAN,
    JAPANESE,
    KOREAN,
    LATIN,
    MODERN_GREEK,
    PORTUGUESE,
    POLISH,
    RUSSIAN,
    SPANISH,
    SWEDISH,
    UKRAINIAN,
}


def decode_ukrainian(text: str) -> str:
    """
    Decode text in Ukrainian.

    Merely replace ASCII "i" symbol with Unicode U+0456.
    """
    return text.replace("i", "і")


def decode_latin(text: str) -> str:
    for symbol, replacement in LATIN_CODE.items():
        text = text.replace(symbol, replacement)
    return text


@dataclass
class LanguageNotFound(Exception):
    code: str


def construct_language(code: str) -> Language:
    for language in KNOWN_LANGUAGES:
        if code == language.get_code():
            return language

    raise LanguageNotFound(code)
