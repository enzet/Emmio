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

ru_upper = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
ru_lower = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
ru = ru_upper + ru_lower

uk_upper = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
uk_lower = "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя"
uk = uk_upper + uk_lower

skippers = "'’"

symbols = {
    "de": latin + "ÄäÖöÜüß",
    "en": latin + "ﬁﬂﬀﬃﬄﬆﬅ",
    "fr": latin + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ" + "’'",
    "la": latin + "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
    "ru": ru,
    "uk": uk + "’'",
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
