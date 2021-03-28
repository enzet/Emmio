"""
Language and font specifics.

Author: Sergey Vartanov (me@enzet.ru).
"""
import re
from typing import Dict, Optional

from iso639 import languages as iso_languages
from iso639.iso639 import _Language as ISOLanguage

DEFAULT_COLOR: str = "#000000"


class Language:
    """
    Natural language description.
    """
    def __init__(
            self, code: str, symbols: Optional[str] = None,
            color: Optional[str] = None):
        self.language: ISOLanguage = iso_languages.get(part1=code)
        self.symbols: Optional[str] = symbols
        self.color: Optional[str] = color

    def __eq__(self, other: "Language"):
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
        """ Check whether language knows its allowed symbols. """
        return self.symbols is not None

    def decode_text(self, text: str) -> str:
        if self.language == ESPERANTO:
            return decode_esperanto(text)
        if self.language == UKRAINIAN:
            return decode_ukrainian(text)
        if self.language == LATIN:
            return decode_latin(text)
        return text


languages = ["de", "en", "fr", "ru"]

LATIN_UPPER: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LATIN_LETTERS: str = LATIN_UPPER + LATIN_UPPER.lower()

RU_UPPER: str = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
UK_UPPER: str = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
EO_UPPER: str = "ABCĈDEFGĜHĤIJĴKLMNOPRSŜTUŬVZ"

SKIPPERS: str = "'’"

LATIN_LIGATURES: Dict[str, str] = {
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
    "en", LATIN_LETTERS + "ÏïÉé" + "".join(LATIN_LIGATURES.keys()),
    color="#021A67")
ESPERANTO: Language = Language(
    "eo", EO_UPPER.lower() + EO_UPPER, color="#009900")
FRENCH: Language = Language(
    "fr",
    LATIN_LETTERS + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ" + SKIPPERS,
    color="#16ACEC")
GERMAN: Language = Language("de", LATIN_LETTERS + "ÄäÖöÜüß", color="#FED12E")
ICELANDIC: Language = Language("is", color="#008844")
ITALIAN: Language = Language("it", LATIN_LETTERS, color="#008888")
JAPANESE: Language = Language("ja", color="#CC2200")
KOREAN: Language = Language("ko", color="#880088")
LATIN: Language = Language(
    "la", LATIN_LETTERS + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ", color="#666666")
MODERN_GREEK: Language = Language("el", color="#444444")
PORTUGUESE: Language = Language("pt", color="#00AA00")
RUSSIAN: Language = Language("ru", RU_UPPER + RU_UPPER.lower(), color="#AAAAAA")
SPANISH: Language = Language(
    "es", LATIN_LETTERS + "ÑÁÉÍÓÚÜñáéíóúü", color="#C61323")
SWEDISH: Language = Language("sv", color="#004488")
UKRAINIAN: Language = Language("uk", UK_UPPER.lower() + UK_UPPER + SKIPPERS)


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
