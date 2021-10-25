from emmio.frequency import FrequencyList
from emmio.language import Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Text:
    """
    Text processing utility.
    """
    def __init__(self, text: str, language: Language):
        """
        :param text: some text to process
        :param language: text language
        """
        self.text: str = text
        self.language: Language = language

    def get_frequency_list(
            self, ignore_proper_nouns: bool = False) -> FrequencyList:
        """
        Construct frequency list of the text.

        :param ignore_proper_nouns: ignore capital letters
        """
        print("Construct frequency list...")

        frequency_list: FrequencyList = FrequencyList()

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
