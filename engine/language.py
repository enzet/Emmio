# -*- coding: utf-8 -*- from __future__ import unicode_literals

most_popular_words = {
    "en": "the",
    "fr": "de",
}

# Language and font specifics.

languages = ["de", "en", "fr", "ru"]

latin = "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvWwXxYyZz"
cyrillic = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ" + \
           "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"

skippers = "'’"

symbols = {
    "en": latin + "ﬁﬂﬀﬃﬄﬆﬅ",
    "fr": latin + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœﬁﬂﬀﬃﬄﬆﬅ",
    "ru": cyrillic,
    "de": latin + "ÄäÖöÜüß",
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
