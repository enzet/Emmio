from emmio.language import symbols
from emmio.frequency import FrequencyList


class Text:

    def __init__(self, text: str, language: str):
        self.text = text
        self.language = language

    def get_frequency_list(self, ignore_proper_nouns=False) -> FrequencyList:
        print("Construct frequency list...")

        possible_symbols = symbols[self.language]

        frequency_list = FrequencyList()
        for line in self.text.split("\n"):
            word = ""
            for c in line:
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
