"""
Language and font specifics.
"""
import re
from typing import Optional

from iso639 import languages as iso_languages
from iso639.iso639 import _Language as ISOLanguage

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DEFAULT_COLOR: str = "#000000"

# COLORS: dict[str, str] = {
#     "ar": "#FF8800",
#     "zh": "#444400",
#     "en": "#021A67",
#     "eo": "#009900",
#     "fr": "#16ACEC",
#     "de": "#FED12E",
#     "is": "#008844",
#     "it": "#008888",
#     "ja": "#CC2200",
#     "ko": "#880088",
#     "la": "#666666",
#     "el": "#444444",
#     "pt": "#00AA00",
#     "ru": "#AAAAAA",
#     "es": "#C61323",
#     "sv": "#004488",
# }


class Language:
    """
    Natural language description.
    """

    def __init__(
        self,
        code: str,
        symbols: Optional[str] = None,
        color: Optional[str] = None,
    ):
        assert color
        self.language: ISOLanguage = iso_languages.get(part1=code)
        self.symbols: Optional[str] = symbols
        self.color: Optional[str] = color

    def __eq__(self, other: "Language"):
        assert isinstance(other, Language)
        return self.language == other.language

    def __hash__(self):
        return hash(self.language.part1)

    def get_name(self) -> str:
        result: str = self.language.name
        result = re.sub(" \\(.*\\)", "", result)
        return result

    def get_color(self) -> str:
        if self.color is not None:
            return self.color
        return DEFAULT_COLOR

    def get_code(self) -> str:
        return self.language.part1

    def get_part3(self) -> str:
        return self.language.part3

    def has_symbol(self, symbol: str) -> bool:
        return symbol in self.symbols

    def has_symbols(self) -> bool:
        """Check whether language knows its allowed symbols."""
        return self.symbols is not None

    def get_symbols(self):
        return self.symbols

    def decode_text(self, text: str) -> str:
        if self == ESPERANTO:
            return decode_esperanto(text)
        if self == UKRAINIAN:
            return decode_ukrainian(text)
        if self == LATIN:
            return decode_latin(text)
        return text


languages = ["de", "en", "fr", "ru"]

LATIN_UPPER: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LATIN_LETTERS: str = LATIN_UPPER + LATIN_UPPER.lower()

RU_UPPER: str = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
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

ARABIC: Language = Language("ar", color="#FF8800")
CHINESE: Language = Language("zh", color="#444400")
ENGLISH: Language = Language(
    "en",
    LATIN_LETTERS + "ÏïÉé" + "".join(LATIN_LIGATURES.keys()),
    color="#2F2FC5",  # #021A67
)
ESPERANTO: Language = Language(
    "eo", EO_UPPER.lower() + EO_UPPER, color="#009900"
)
FRENCH: Language = Language(
    "fr",
    LATIN_LETTERS + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ" + SKIPPERS,
    color="#4DA9CC",  # #16ACEC
)
GERMAN: Language = Language("de", LATIN_LETTERS + "ÄäÖöÜüß", color="#C3A656")  # #FED12E
ICELANDIC: Language = Language("is", color="#008844")
ITALIAN: Language = Language("it", LATIN_LETTERS, color="#008888")
JAPANESE: Language = Language("ja", color="#CC2200")
KOREAN: Language = Language("ko", color="#880088")
LATIN: Language = Language(
    "la", LATIN_LETTERS + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ", color="#666666"
)
MODERN_GREEK: Language = Language("el", color="#444444")
PORTUGUESE: Language = Language("pt", color="#00AA00")
POLISH: Language = Language("pl", color="#00AA00")
RUSSIAN: Language = Language("ru", RU_UPPER + RU_UPPER.lower(), color="#AAAAAA")
SPANISH: Language = Language(
    "es", LATIN_LETTERS + "ÑÁÉÍÓÚÜñáéíóúü", color="#CB3636"  # "C61323"
)
SWEDISH: Language = Language("sv", color="#004488")
UKRAINIAN: Language = Language("uk", UK_UPPER.lower() + UK_UPPER + SKIPPERS, color="#E5D144")

known_languages = [
    ARABIC,
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
]

def decode_ukrainian(text: str) -> str:
    return text.replace("i", "і")  # i to U+0456


def decode_esperanto(text: str) -> str:
    digraphs = {
        "cx": "ĉ",
        "gx": "ĝ",
        "hx": "ĥ",
        "jx": "ĵ",
        "sx": "ŝ",
        "ux": "ŭ",
    }
    for digraph in digraphs:
        text = text.replace(digraph, digraphs[digraph])

    return text


def decode_latin(text: str) -> str:
    return text.replace("ā", "a").replace("ō", "o")


def construct_language(code: str) -> Language:
    for language in known_languages:
        if code == language.get_code():
            return language

    return Language(code)
