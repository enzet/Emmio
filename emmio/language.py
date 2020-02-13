"""
Emmio.

Author: Sergey Vartanov (me@enzet.ru)
"""
most_popular_words = {
    "en": "the",
    "fr": "de",
}

# Language and font specifics.

languages = ["de", "en", "fr", "ru"]

latin_upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
latin_lower = "abcdefghijklmnopqrstuvwxyz"
latin = latin_upper + latin_lower

cyrillic_upper = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
cyrillic_lower = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
cyrillic = cyrillic_upper + cyrillic_lower

skippers = "'’"

symbols = {
    "de": latin + "ÄäÖöÜüß",
    "en": latin + "ﬁﬂﬀﬃﬄﬆﬅ",
    "fr": latin + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ",
    "la": latin + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
    "ru": cyrillic,
}

ligatures = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬆ": "st",
    "ﬅ": "ft",
}
