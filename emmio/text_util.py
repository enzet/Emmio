"""Text processing utility."""

import logging
from collections import defaultdict
from typing import IO

from emmio.language import Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Text:
    """Text processing utility."""

    def __init__(self, input_file: IO[str], language: Language):
        """
        :param input_file: file to process
        :param language: text language
        """
        self.input_file: IO[str] = input_file
        self.language: Language = language

    def get_frequency_list(self) -> dict[str, int]:
        """Construct frequency list of the text."""
        logging.info("Construct frequency list...")

        result: dict[str, int] = defaultdict(int)

        word: str = ""
        for line in self.input_file:
            symbol: str
            for symbol in line:
                # We can replace it with `self.language.has_symbol(symbol)`.
                if (
                    "\u0561" <= symbol <= "\u0587"
                    or "\u0531" <= symbol <= "\u0556"
                ):
                    word += symbol
                else:
                    if word:
                        result[word.lower()] += 1
                    word = ""

        return result


def sanitize(text: str, words_to_hide: list[str], sanitizer: str) -> str:
    """Replace word in text with hiding symbols."""

    for word in words_to_hide:
        sanitized: str = sanitizer * len(word)

        start: int
        if "́" in text:
            if word in text.replace("́", ""):
                start = text.replace("́", "").find(word)
                text = text[:start] + sanitized + text[start + len(word) + 1 :]

        text = text.replace(word, sanitized)

        while word.lower() in text.lower():
            start = text.lower().find(word.lower())
            text = text[:start] + sanitized + text[start + len(word) :]

    return text
