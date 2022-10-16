import sys
from collections import defaultdict
from pathlib import Path
from typing import IO

from emmio.frequency import FrequencyList
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
        for line in input_file:
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


if __name__ == "__main__":
    input_path: Path = Path(sys.argv[1])
    output_path: Path = Path(sys.argv[2])
    language: str = sys.argv[3]

    with input_path.open() as input_file:
        text = Text(input_file, language=construct_language(language))
        m = text.get_frequency_list()

    with output_path.open("w+") as output_file:
        for word in sorted(m.keys(), key=lambda x: -m[x]):
            output_file.write(f"{word} {m[word]}\n")
