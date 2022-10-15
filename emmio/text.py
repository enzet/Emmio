import sys
from pathlib import Path

from emmio.frequency import FrequencyList
from emmio.language import Language, construct_language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Text:
    """Text processing utility."""

    def __init__(self, text: str, language: Language):
        """
        :param text: some text to process
        :param language: text language
        """
        self.text: str = text
        self.language: Language = language

    def get_frequency_list(
        self, ignore_proper_nouns: bool = False
    ) -> FrequencyList:
        """
        Construct frequency list of the text.

        :param ignore_proper_nouns: ignore capital letters
        """
        print("Construct frequency list...")

        frequency_list: FrequencyList = FrequencyList(update=False)

        for line in self.text.split("\n"):
            line: str
            word: str = ""
            for symbol in line:
                symbol: str
                if self.language.has_symbol(symbol):
                    word += symbol
                    continue
                if word != "":
                    if ignore_proper_nouns:
                        frequency_list.add(word[0] + word[1:].lower())
                    else:
                        frequency_list.add(word.lower())
                word = ""

        if ignore_proper_nouns:
            frequency_list.ignore_proper_nouns()

        return frequency_list


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
        text = Text(input_file.read(), language=construct_language(language))

    frequency_list: FrequencyList = text.get_frequency_list()
    frequency_list.write_list(output_path)
