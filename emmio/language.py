"""
Emmio.

Author: Sergey Vartanov (me@enzet.ru)
"""
import re
from typing import Dict

from iso639.iso639 import _Language as ISOLanguage
from iso639 import languages as iso_languages

most_popular_words: Dict[str, str] = {
    "en": "the",
    "fr": "de",
}

# Language and font specifics.

languages = ["de", "en", "fr", "ru"]

LATIN_UPPER: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LATIN_LOWER: str = "abcdefghijklmnopqrstuvwxyz"
LATIN: str = LATIN_UPPER + LATIN_LOWER

RU_UPPER: str = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
RU_LOWER: str = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"

UK_UPPER: str = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
UK_LOWER: str = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"

EO_UPPER: str = "ABCĈDEFGĜHĤIJĴKLMNOPRSŜTUŬVZ"
EO_LOWER: str = "abcĉdefgĝhĥijĵklmnoprsŝtuŭvz"

SKIPPERS: str = "'’"

symbols: Dict[str, str] = {
    "de": LATIN + "ÄäÖöÜüß",
    "en": LATIN + "ﬁﬂﬀﬃﬄﬆﬅÏïÉé",
    "eo": EO_LOWER + EO_UPPER,
    "es": LATIN + "ÑÁÉÍÓÚÜñáéíóúü",
    "fr": LATIN + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ" + SKIPPERS,
    "it": LATIN,
    "la": LATIN + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
    "ru": RU_UPPER + RU_LOWER,
    "uk": UK_LOWER + UK_UPPER + SKIPPERS,
}

LIGATURES: Dict[str, str] = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬆ": "st",
    "ﬅ": "ft",
}


COLORS: Dict[str, str] = {
    "ar": "#FF8800",  # "FF8800", "A71E49",
    "de": "#FED12E",  # "#DD4444",  # "000000", "E34C26",
    "el": "#444444",  # "444444", "CD6400",
    "en": "#021A67",  # "#448888",  # "008800", "178600",
    "eo": "#009900",  # "#AA0000",  # "AA0000", "003FA2",
    "es": "#C61323",  # "#CC9977",  # "888800", "B30000",
    "fr": "#16ACEC",  # "#444466",  # "0000FF", "3572A5",
    "is": "#008844",  # "008844", "A78649",
    "it": "#008888",  # "008888", "F34B7D",
    "ja": "#CC2200",  # "FF0000", "28430A",
    "ko": "#880088",  # "880088", "652B81",
    "la": "#666666",  # "00AA00", "00ADD8",
    "pt": "#00AA00",  # "00AA00", "00ADD8",
    "ru": "#AAAAAA",  # "AAAAAA", "e4cc98",
    "sv": "#004488",  # "004488", "358a5b",
    "zh": "#444400",  # "444400", "b2b7f8",
}


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


class Language:
    def __init__(self, code: str):
        self.language: ISOLanguage = iso_languages.get(part1=code)

    def get_name(self):
        result: str = self.language.name
        result = re.sub(" \\(.*\\)", "", result)
        return result

    def get_color(self):
        if self.language.part1 in COLORS:
            return COLORS[self.language.part1]
        return "#000000"

    def get_code(self) -> str:
        return self.language.part1

    def get_symbols(self):
        return symbols[self.language.part1]
