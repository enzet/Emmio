"""
Emmio.

Author: Sergey Vartanov (me@enzet.ru)
"""
from typing import Dict

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
    "fr": LATIN + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ" + SKIPPERS,
    "la": LATIN + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
    "ru": RU_UPPER + RU_LOWER,
    "uk": UK_LOWER + UK_UPPER + SKIPPERS,
    "eo": EO_LOWER + EO_UPPER,
    "it": LATIN,
    "es": LATIN + "ÑÁÉÍÓÚÜñáéíóúü"
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


def decode_esperanto(text: str) -> str:
    digraphs = {
        "cx": "ĉ",
        "gx": "ĝ",
        "hx": "ĥ",
        "jx": "ĵ",
        "sx": "ŝ",
        "ux": "ŭ"
    }
    for digraph in digraphs:
        text = text.replace(digraph, digraphs[digraph])

    return text


class Language:
    def get_name(self):
        result: str = self.language.name
