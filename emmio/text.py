from emmio.language import symbols
from emmio.frequency import FrequencyList


class Text:
    """
    Text processing utility.
    """

    def __init__(self, text: str, language: str):
        """
        :param text: some text to process.
        :param language: 2-letters ISO 639-1 language code.
        """
        self.text: str = text
        self.language: str = language

    def get_frequency_list(self, ignore_proper_nouns: bool = False) \
            -> FrequencyList:
        """
        Construct frequency list of the text.

        :param ignore_proper_nouns: ignore capital letters.
        """
        print("Construct frequency list...")

        possible_symbols: str = symbols[self.language]
        frequency_list = FrequencyList()

        for line in self.text.split("\n"):  # type: str
            word: str = ""
            for c in line:  # type: str
                if c in possible_symbols:
                    word += c
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
