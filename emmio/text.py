from argparse import Namespace
from collections import defaultdict
from pathlib import Path
from typing import IO

from emmio.language import Language, construct_language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Text:
    """Text processing utility."""

    def __init__(self, input_file: IO, language: Language):
        """
        :param input_file: file to process
        :param language: text language
        """
        self.input_file: IO = input_file
        self.language: Language = language

    def get_frequency_list(self) -> dict:
        """Construct frequency list of the text."""
        print("Construct frequency list...")
        check = self.language.has_symbol

        # frequency_list: FrequencyList = FrequencyList(update=False)
        m = defaultdict(int)

        word: str = ""
        for line in self.input_file:
            for symbol in line:
                symbol: str
                if (
                    "\u0561" <= symbol <= "\u0587"
                    or "\u0531" <= symbol <= "\u0556"
                ):
                    word += symbol
                # if check(symbol):
                #     word += symbol
                #     continue
                else:
                    if word:
                        m[word.lower()] += 1
                    word = ""

        return m


def sanitize(text: str, words_to_hide: list[str], sanitizer: str) -> str:
    """Replace word in text with hiding symbols."""

    for word in words_to_hide:
        sanitized: str = sanitizer * len(word)

        if "́" in text:
            if word in text.replace("́", ""):
                start: int = text.replace("́", "").find(word)
                text = text[:start] + sanitized + text[start + len(word) + 1 :]

        text = text.replace(word, sanitized)

        while word.lower() in text.lower():
            start: int = text.lower().find(word.lower())
            text = text[:start] + sanitized + text[start + len(word) :]

    return text


def construct_frequency_list(emmio_data: "Emmio", arguments: Namespace) -> None:
    input_path: Path = Path(arguments.input)
    frequency_list_id: str = arguments.id
    language: str = arguments.language

    with input_path.open() as input_file:
        text = Text(input_file, language=construct_language(language))
        m = text.get_frequency_list()

    emmio_data.add_frequency_list(frequency_list_id, m)
