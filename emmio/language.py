"""Language and font specifics."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

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

# Simplified spellings per language code. When the proper characters are not
# available, these ASCII sequences are commonly used instead. Each maps such a
# sequence back to the character it may stand for, so that a word typed in the
# simplified form can be matched against its proper spelling.
# fmt: off
VARIANT_SUBSTITUTIONS: dict[str, dict[str, str]] = {
    # German umlauts and eszett.
    "de": {"ae": "ä", "oe": "ö", "ue": "ü", "ss": "ß"},
    # Esperanto x-system and h-system. The h-system has no unambiguous form
    # for "ŭ" (it is written as a bare "u"), so only "ux" recovers it.
    "eo": {
        "cx": "ĉ", "gx": "ĝ", "hx": "ĥ", "jx": "ĵ", "sx": "ŝ", "ux": "ŭ",
        "ch": "ĉ", "gh": "ĝ", "hh": "ĥ", "jh": "ĵ", "sh": "ŝ",
    },
    # Icelandic ligature and thorn/eth.
    "is": {"ae": "æ", "th": "þ", "dh": "ð"},
    # Norwegian letters.
    "no": {"aa": "å", "ae": "æ", "oe": "ø"},
    "nb": {"aa": "å", "ae": "æ", "oe": "ø"},
    # Swedish letters.
    "sv": {"aa": "å", "ae": "ä", "oe": "ö"},
}
# fmt: on


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
    """All symbols allowed in native words of the language."""

    borrowed_symbols: str = ""
    """Symbols allowed in the language, but not in its native words.

    Letters that appear only in borrowed words, proper names, or variant
    orthography: e.g. "j", "k", "w", "x", "y" in Italian are used in words
    like "weekend", but never in native Italian words.
    """

    self_name: str | None = None
    """Language name in its own language."""

    parent: Language | None = None
    """Parent language."""

    checking: Callable[[str], bool] | None = None
    """Check if the symbol is allowed in the language."""

    def __post_init__(self) -> None:
        self.iso639_language: ISO639Language = ISO639Language(self.code)

        self.has_symbol: Callable[[str], bool]
        if self.checking:
            self.has_symbol = self.checking
        else:
            self.has_symbol = (
                lambda symbol: symbol in self.symbols
                or symbol in self.borrowed_symbols
            )

    @classmethod
    def from_code(cls, code: str) -> Language:
        """Get language by its code.

        :param code: ISO 639-1:2002 two-letter code
        """
        for language in KnownLanguages.get_languages():
            if code == language.get_code():
                return language

        raise LanguageNotFoundError(code)

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
        """Get all symbols allowed in the language, including borrowed."""
        if not self.has_symbols():
            return None
        return self.symbols + self.borrowed_symbols

    def is_word(self, word: str) -> bool:
        """Check if the word is valid in the language.

        Borrowed letters are allowed: e.g. Italian "weekend" is a word.
        """
        if not self.has_symbols():
            msg = f"Language `{self.get_code()}` does not have symbols."
            raise ValueError(msg)
        return all(self.has_symbol(c) for c in word)

    def is_native_word(self, word: str) -> bool:
        """Check if the word contains only native alphabet letters.

        Borrowed letters (see `borrowed_symbols`) make a word a probable
        borrowing, not a native word: e.g. Italian "weekend".
        """
        if not self.has_symbols():
            msg = f"Language `{self.get_code()}` does not have symbols."
            raise ValueError(msg)
        return all(c in self.symbols for c in word)

    def normalize(self, word: str) -> str:
        """Get the most common form of the word.

        E.g. for Latin, the normal form of "lītera" is "litera".
        """
        if self == KnownLanguages.ARMENIAN:
            return word.lower().replace("՞", "").replace("՛", "")
        if self == KnownLanguages.LATIN:
            word = word.lower().replace("æ", "ae")
            for symbol, replacement in LATIN_CODE.items():
                word = word.replace(symbol, replacement)
            return word
        if self == KnownLanguages.RUSSIAN:
            return word.lower().replace("́", "").replace("ё", "е")
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

    def encode_texts(self, text: str) -> list[str]:
        """Get simplified spellings that decode back to the text.

        Inverse of `decode_text` for languages with digraphs: one variant per
        encoding system, e.g. Esperanto "anstataŭ" is represented both as
        "anstataux" (x-system) and "anstatauh" (h-system). The text itself is
        never included.
        """
        if self.get_code() not in DIGRAPHS:
            return []

        # Group typed sequences by the character they decode to: each group
        # lists the character's spelling in every encoding system, in the
        # order the systems appear in `digraphs.json`.
        spellings: dict[str, list[str]] = {}
        for digraph, character in DIGRAPHS[self.get_code()].items():
            spellings.setdefault(character, []).append(digraph)

        variants: list[str] = []
        for system in range(max(map(len, spellings.values()))):
            variant: str = text
            for character, digraphs in spellings.items():
                variant = variant.replace(
                    character, digraphs[min(system, len(digraphs) - 1)]
                )
            if variant != text and variant not in variants:
                variants.append(variant)

        return variants

    def __repr__(self) -> str:
        return self.get_code()

    def get_random_color(self) -> str:
        """Get random color for the language."""
        return "#" + str(hex(abs(hash(self.get_code()))))[2:8]

    def get_variants(self, word: str) -> list[str]:
        """Get words that may be represented by the given word.

        Some words are written using a simplified spelling (e.g. when the
        proper characters are not available). This method tries to recover the
        original words that such a spelling may stand for.
        """

        variants: list[str] = []

        if self == KnownLanguages.LATIN:
            decoded = self.decode_text(word)
            if decoded != word:
                variants.append(decoded)
        if self == KnownLanguages.GERMAN and word[0].upper() != word[0]:
            variants.append(word[0].upper() + word[1:])

        for sequence, character in VARIANT_SUBSTITUTIONS.get(
            self.get_code(), {}
        ).items():
            pattern: re.Pattern[str] = re.compile(
                re.escape(sequence), re.IGNORECASE
            )
            if not pattern.search(word):
                continue

            def replace(
                match: re.Match[str], character: str = character
            ) -> str:
                # Match the case of the replaced sequence: a leading uppercase
                # letter (e.g. "Oe" or "OE") yields an uppercase character.
                return (
                    character.upper()
                    if match.group()[0].isupper()
                    else character
                )

            variants.append(pattern.sub(replace, word))

        return variants


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
ARABIC_LETTERS: str = letter_range("\u0620", "\u06ff")  # TODO(enzet): check.
KOREAN_LETTERS: str = letter_range("\u1100", "\u11ff") + letter_range(
    "\uac00", "\ud7a3"
)
JAPANESE_LETTERS: str = KATAKANA + HIRAGANA + KANJI
ARMENIAN_LETTERS: str = letter_range("\u0561", "\u0587") + letter_range(
    "\u0531", "\u0556"
)

# Whole Unicode blocks, used as best-effort alphabets for languages written in
# these scripts (the same technique as Arabic, Korean, and Japanese above).
CYRILLIC_LETTERS: str = letter_range("\u0400", "\u04ff")  # Bulgarian, etc.
DEVANAGARI_LETTERS: str = letter_range("\u0900", "\u097f")  # Hindi.
BENGALI_LETTERS: str = letter_range("\u0980", "\u09ff")
TAMIL_LETTERS: str = letter_range("\u0b80", "\u0bff")
TELUGU_LETTERS: str = letter_range("\u0c00", "\u0c7f")
MALAYALAM_LETTERS: str = letter_range("\u0d00", "\u0d7f")
SINHALA_LETTERS: str = letter_range("\u0d80", "\u0dff")
THAI_LETTERS: str = letter_range("\u0e00", "\u0e7f")

LATIN_UPPER: str = letter_range("A", "Z")
LATIN_LETTERS: str = LATIN_UPPER + LATIN_UPPER.lower()


def both_cases(letters: str) -> str:
    """Get the letters with their lowercase forms appended."""
    return letters + letters.lower()


def latin_letters_except(excluded: str) -> str:
    """Get Latin letters of both cases without the excluded uppercase ones."""
    return both_cases(
        "".join(letter for letter in LATIN_UPPER if letter not in excluded)
    )


RU_UPPER: str = letter_range("А", "Я") + "Ё"
UK_UPPER: str = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
EO_UPPER: str = "ABCĈDEFGĜHĤIJĴKLMNOPRSŜTUŬVZ"

SKIPPERS: str = "'’"
STRESS_MARK: str = "́"
"""Stress mark in Russian, Ukrainian, and some other languages.

It is not an alphabet letter, but it may be used in text to mark the stressed
syllable.
"""

LATIN_LIGATURES: dict[str, str] = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬆ": "st",
    "ﬅ": "ft",
}


def hy_checking(symbol: str) -> bool:
    """Check for Armenian symbols."""
    return (
        "\u0561" <= symbol <= "\u0587"
        or "\u0531" <= symbol <= "\u0556"
        or symbol in ["՞", "՛"]
    )


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
        checking=hy_checking,
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
        LATIN_LETTERS + "".join(LATIN_LIGATURES.keys()),
        # Diacritics appear only in borrowed spellings, e.g. "café", "naïve".
        borrowed_symbols=both_cases("ÉÏ"),
    )
    ESPERANTO: Language = Language(
        "eo",
        Color("#44982A"),  # Green color of the Esperanto flag.
        EO_UPPER.lower() + EO_UPPER,
    )
    FRENCH: Language = Language(
        "fr",
        Color("#4193C3"),  # Blue color of the Francophonie flag.
        latin_letters_except("KW")
        + "ÂÀÇÉÈÊËÎÏÔÙÛÜŸÆŒàâçéèêëîïôùûüÿæœ"
        + "".join(LATIN_LIGATURES.keys()),
        # K and W appear only in borrowed words, e.g. "kilo", "wagon".
        borrowed_symbols=both_cases("KW"),
        self_name="français",
    )
    GERMAN: Language = Language(
        "de",
        Color("#F7D046"),  # Yellow color of the German flag.
        latin_letters_except("Y") + "ÄäÖöÜüß",
        # Y appears only in borrowed words, e.g. "Typ", "Yacht".
        borrowed_symbols=both_cases("Y"),
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
        letter_range("\u0590", "\u05f4") + "-",
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
        # 21-letter native alphabet with standard accented vowels.
        latin_letters_except("JKWXY") + both_cases("ÀÈÉÌÒÙ"),
        # J, K, W, X, Y appear only in borrowed words and proper names;
        # í, î, ó, ú only in variant orthography, e.g. "principî".
        borrowed_symbols=both_cases("JKWXYÍÎÓÚ"),
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
        "AaBbCcDdEeFfGgHhIiJjKkLlMmNnOoPpQqRrSsTtUuVvXxYyZz"  # Without "W".
        "ÁÉÍÓÚÝĀĒĪŌŪȲáéíóúýāēīōūȳ",
        self_name="latina",
    )
    MODERN_GREEK: Language = Language(
        "el",
        Color("#2A5DA9"),  # Blue color of the Greece flag.
        "ΑαΒβΓγΔδΕεΖζΗηΘθΙιΚκΛλΜμΝνΞξΟοΠπΡρΣσςΤτΥυΦφΧχΨψΩω"
        + letter_range("\u1f00", "\u1fff")
        + "ΆάΈέΉήΊίΌόΎύΏώ",
        self_name="ελληνικά",
    )
    NORWEGIAN: Language = Language(
        "no",
        Color("#061A57"),  # Blue color of the Norway flag.
        latin_letters_except("CQWXZ") + "ÆØÅæøå",
        # C, Q, W, X, Z appear only in borrowed words, e.g. "camping", "quiz".
        borrowed_symbols=both_cases("CQWXZ"),
        self_name="norsk",
    )
    NORWEGIAN_BOKMAL: Language = Language(
        "nb",
        Color("#061A57"),  # Blue color of the Norway flag.
        latin_letters_except("CQWXZ") + "ÆØÅæøå",
        borrowed_symbols=both_cases("CQWXZ"),
        self_name="norsk bokmål",
        parent=NORWEGIAN,
    )
    PORTUGUESE: Language = Language(
        "pt",
        Color("#2B6519"),  # Green color of the Portugal flag.
        latin_letters_except("KWY") + "ÁÂÃ̃ÀÇÉÊÍÓÔÕÚáâã̃àçéêíóôõú",
        # K, W, Y appear only in borrowed words, e.g. "kiwi", "yoga".
        borrowed_symbols=both_cases("KWY"),
        self_name="português",
    )
    POLISH: Language = Language(
        "pl",
        Color("#CB2E3F"),  # Red color of the Poland flag.
        latin_letters_except("QVX") + both_cases("ĄĆĘŁŃÓŚŹŻ"),
        # Q, V, X appear only in borrowed words, e.g. "quiz", "video".
        borrowed_symbols=both_cases("QVX"),
        self_name="polski",
    )
    RUSSIAN: Language = Language(
        "ru",
        Color("#1335A1"),  # Blue color of the Russia flag.
        RU_UPPER + RU_UPPER.lower() + STRESS_MARK,
        self_name="русский",
    )
    SPANISH: Language = Language(
        "es",
        Color("#F6C844"),  # Yellow color of the Spain flag.
        latin_letters_except("KW") + "ÑÁÉÍÓÚÜñáéíóúü",
        # K and W appear only in borrowed words, e.g. "kilo", "web".
        borrowed_symbols=both_cases("KW"),
        self_name="español",
    )
    SWEDISH: Language = Language(
        "sv",
        Color("#205090"),  # Blue color of the Sweden flag.
        latin_letters_except("QWZ") + "ÅÄÖåäö",
        # Q, W, Z appear only in borrowed words, e.g. "quiz", "webb", "zon".
        borrowed_symbols=both_cases("QWZ"),
        self_name="svenska",
    )
    UKRAINIAN: Language = Language(
        "uk",
        Color("#F9D849"),  # Yellow color of the Ukrainian flag.
        UK_UPPER.lower() + UK_UPPER + SKIPPERS + STRESS_MARK,
        self_name="українська",
    )

    # Languages below are defined best-effort (Unicode script blocks and
    # standard diacritics, representative flag colors) to support lexicon
    # creation for every language with downloadable FrequencyWords and Tatoeba
    # artifacts; alphabets and colors can be refined later.
    AFRIKAANS: Language = Language(
        "af",
        Color("#007A4D"),  # Green color of the South African flag.
        latin_letters_except("CQXZ") + "ÁÄÉÈÊËÍÎÏÓÔÖÚÛÜÝáäéèêëíîïóôöúûüý",
        borrowed_symbols=both_cases("CQXZ"),
        self_name="Afrikaans",
    )
    ALBANIAN: Language = Language(
        "sq",
        Color("#E41E20"),  # Red color of the Albanian flag.
        latin_letters_except("W") + "ÇËçë",
        borrowed_symbols=both_cases("W"),
        self_name="shqip",
    )
    BASQUE: Language = Language(
        "eu",
        Color("#D52B1E"),  # Red color of the Basque flag.
        latin_letters_except("CQVWY") + "ÑÜñü",
        # Ç is officially reserved for borrowed words, like C, Q, V, W, Y.
        borrowed_symbols=both_cases("CQVWYÇ"),
        self_name="euskara",
    )
    BENGALI: Language = Language(
        "bn",
        Color("#006A4E"),  # Green color of the Bangladeshi flag.
        BENGALI_LETTERS,
        self_name="বাংলা",
    )
    BOSNIAN: Language = Language(
        "bs",
        Color("#002F6C"),  # Blue color of the Bosnian flag.
        latin_letters_except("QWXY") + "ČĆĐŠŽčćđšž",
        borrowed_symbols=both_cases("QWXY"),
        self_name="bosanski",
    )
    BRETON: Language = Language(
        "br",
        Color("#000000"),  # Black stripes of the Breton flag.
        LATIN_LETTERS + "ÂÊÎÔÛÜÙÑñâêîôûüù",
        self_name="brezhoneg",
    )
    BULGARIAN: Language = Language(
        "bg",
        Color("#00966E"),  # Green color of the Bulgarian flag.
        CYRILLIC_LETTERS,
        self_name="български",
    )
    CATALAN: Language = Language(
        "ca",
        Color("#FCDD09"),  # Yellow color of the Catalan flag.
        latin_letters_except("KW") + "ÀÇÉÈÍÏÓÒÚÜ·àçéèíïóòúü",
        borrowed_symbols=both_cases("KW"),
        self_name="català",
    )
    CROATIAN: Language = Language(
        "hr",
        Color("#D6001C"),  # Red color of the Croatian flag.
        latin_letters_except("QWXY") + "ČĆĐŠŽčćđšž",
        borrowed_symbols=both_cases("QWXY"),
        self_name="hrvatski",
    )
    CZECH: Language = Language(
        "cs",
        Color("#11457E"),  # Blue color of the Czech flag.
        latin_letters_except("QWX") + "ÁČĎÉĚÍŇÓŘŠŤÚŮÝŽáčďéěíňóřšťúůýž",
        borrowed_symbols=both_cases("QWX"),
        self_name="čeština",
    )
    DANISH: Language = Language(
        "da",
        Color("#C60C30"),  # Red color of the Danish flag.
        latin_letters_except("CQWXZ") + "ÆØÅæøå",
        borrowed_symbols=both_cases("CQWXZ"),
        self_name="dansk",
    )
    DUTCH: Language = Language(
        "nl",
        Color("#AE1C28"),  # Red color of the Dutch flag.
        latin_letters_except("QXY") + "ÁÄÉËÍÏÓÖÚÜĲĳáäéëíïóöúü",
        borrowed_symbols=both_cases("QXY"),
        self_name="Nederlands",
    )
    ESTONIAN: Language = Language(
        "et",
        Color("#0072CE"),  # Blue color of the Estonian flag.
        latin_letters_except("CFQWXYZ") + "ÕÄÖÜõäöü",
        # F, Š, Z, Ž are official "foreign letters" of the alphabet; C, Q, W,
        # X, Y are used only in foreign proper names.
        borrowed_symbols=both_cases("CFQWXYZŠŽ"),
        self_name="eesti",
    )
    FINNISH: Language = Language(
        "fi",
        Color("#003580"),  # Blue color of the Finnish flag.
        latin_letters_except("CQWXZ") + "ÄÖäö",
        # Å is used only in Swedish names; Š and Ž only in borrowed words.
        borrowed_symbols=both_cases("CQWXZÅŠŽ"),
        self_name="suomi",
    )
    GALICIAN: Language = Language(
        "gl",
        Color("#0066CC"),  # Blue color of the Galician flag.
        latin_letters_except("JKWY") + "ÁÉÍÓÚÜÑñáéíóúü",
        borrowed_symbols=both_cases("JKWY"),
        self_name="galego",
    )
    HINDI: Language = Language(
        "hi",
        Color("#FF9933"),  # Saffron color of the Indian flag.
        DEVANAGARI_LETTERS,
        self_name="हिन्दी",
    )
    HUNGARIAN: Language = Language(
        "hu",
        Color("#CD2A3E"),  # Red color of the Hungarian flag.
        # Y stays native: it is part of the digraphs "gy", "ly", "ny", "ty".
        latin_letters_except("QWX") + "ÁÉÍÓÖŐÚÜŰáéíóöőúüű",
        borrowed_symbols=both_cases("QWX"),
        self_name="magyar",
    )
    INDONESIAN: Language = Language(
        "id",
        Color("#CE1126"),  # Red color of the Indonesian flag.
        latin_letters_except("QX"),
        borrowed_symbols=both_cases("QX"),
        self_name="bahasa Indonesia",
    )
    KAZAKH: Language = Language(
        "kk",
        Color("#00AFCA"),  # Sky-blue color of the Kazakh flag.
        CYRILLIC_LETTERS,
        self_name="қазақ тілі",
    )
    LITHUANIAN: Language = Language(
        "lt",
        Color("#FDB913"),  # Yellow color of the Lithuanian flag.
        latin_letters_except("QWX") + "ĄČĘĖĮŠŲŪŽąčęėįšųūž",
        borrowed_symbols=both_cases("QWX"),
        self_name="lietuvių",
    )
    MACEDONIAN: Language = Language(
        "mk",
        Color("#D20000"),  # Red color of the Macedonian flag.
        CYRILLIC_LETTERS,
        self_name="македонски",
    )
    MALAYALAM: Language = Language(
        "ml",
        Color("#00843D"),  # Green representative color.
        MALAYALAM_LETTERS,
        self_name="മലയാളം",
    )
    ROMANIAN: Language = Language(
        "ro",
        Color("#002B7F"),  # Blue color of the Romanian flag.
        latin_letters_except("KQWY") + "ÂĂÎȘȚâăîșț",
        borrowed_symbols=both_cases("KQWY"),
        self_name="română",
    )
    SERBIAN: Language = Language(
        "sr",
        Color("#C6363C"),  # Red color of the Serbian flag.
        CYRILLIC_LETTERS,
        self_name="српски",
    )
    SINHALA: Language = Language(
        "si",
        Color("#FFB700"),  # Golden color of the Sri Lankan flag.
        SINHALA_LETTERS,
        self_name="සිංහල",
    )
    SLOVAK: Language = Language(
        "sk",
        Color("#0B4EA2"),  # Blue color of the Slovak flag.
        latin_letters_except("QWX") + "ÁÄČĎÉÍĹĽŇÓÔŔŠŤÚÝŽáäčďéíĺľňóôŕšťúýž",
        borrowed_symbols=both_cases("QWX"),
        self_name="slovenčina",
    )
    SLOVENIAN: Language = Language(
        "sl",
        Color("#005DA4"),  # Blue color of the Slovenian flag.
        latin_letters_except("QWXY") + "ČŠŽčšž",
        borrowed_symbols=both_cases("QWXY"),
        self_name="slovenščina",
    )
    TAGALOG: Language = Language(
        "tl",
        Color("#0038A8"),  # Blue color of the Philippine flag.
        LATIN_LETTERS + "Ññ",
        self_name="Tagalog",
    )
    TAMIL: Language = Language(
        "ta",
        Color("#C8102E"),  # Red representative color.
        TAMIL_LETTERS,
        self_name="தமிழ்",
    )
    TELUGU: Language = Language(
        "te",
        Color("#F5A800"),  # Golden representative color.
        TELUGU_LETTERS,
        self_name="తెలుగు",
    )
    THAI: Language = Language(
        "th",
        Color("#2D2A4A"),  # Blue color of the Thai flag.
        THAI_LETTERS,
        self_name="ไทย",
    )
    TURKISH: Language = Language(
        "tr",
        Color("#E30A17"),  # Red color of the Turkish flag.
        latin_letters_except("QWX") + "ÇĞİıÖŞÜçğöşü",
        borrowed_symbols=both_cases("QWX"),
        self_name="Türkçe",
    )
    URDU: Language = Language(
        "ur",
        Color("#01411C"),  # Green color of the Pakistani flag.
        ARABIC_LETTERS,
        self_name="اردو",
    )
    VIETNAMESE: Language = Language(
        "vi",
        Color("#DA251D"),  # Red color of the Vietnamese flag.
        latin_letters_except("FJWZ")
        + "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝàáâãèéêìíòóôõùúýĂăĐđĨĩŨũƠơƯư"
        + letter_range("ạ", "ỹ"),
        borrowed_symbols=both_cases("FJWZ"),
        self_name="Tiếng Việt",
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
class LanguageNotFoundError(ValueError):
    """Language with the given code was not found."""

    code: str
    """ISO 639-1:2002 two-letter code."""
