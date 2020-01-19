import random

from emmio import ui


class WordOccurrences:
    def __init__(self, word: str, occurrences: int):
        self.word = word
        self.occurrences = occurrences


class FrequencyList:
    """
    Frequency list of some text.
    """
    def __init__(self):
        self.data = {}
        self.occurrences = 0
        self.sorted_keys = None

    def __len__(self):
        return len(self.data)

    def read(self, file_name: str, file_format: str):
        if file_format == "yaml":
            self.read_yaml(file_name)
        elif file_format == "text":
            self.read_list(file_name)
        else:
            raise Exception

    def read_yaml(self, file_name: str):
        """
        Read file with frequency in the format:
        `<word>: <number of occurrences>`

        :param file_name: input YAML file name
        """
        ui.write("Reading YAML frequency list from " + file_name + "...")

        try:
            self.read_list(file_name, ": ")
        except Exception:
            import yaml
            structure = yaml.load(open(file_name, "r"))

            for word in structure:
                self.data[word] = structure[word]

        self.sort()

    def read_list(self, file_name: str, delimiter: str=" "):
        """
        Read file with frequency in the format:
        `<word><delimiter><number of occurrences>`

        :param file_name: input text file name
        :param delimiter: delimiter between word and its number of occurrences
        """
        ui.write("Reading frequency list from " + file_name + "...")

        lines = open(file_name).readlines()
        lines_number = len(lines)
        length = len(delimiter)

        for index, line in enumerate(lines):
            ui.progress_bar(index, lines_number)
            position = line.find(delimiter)
            word = line[:position]
            occurrences = int(line[position + length:])
            self.data[word] = occurrences
            self.occurrences += occurrences
        ui.progress_bar(-1, 0)

        self.sort()

    def write_list(self, file_name: str) -> None:
        with open(file_name, 'w+') as output:
            for word in sorted(self.data.keys(), key=lambda x: -self.data[x]):
                output.write(word + ' ' + str(self.data[word]) + '\n')

    def add(self, word):
        if word in self.data:
            self.data[word] += 1
        else:
            self.data[word] = 1

        self.occurrences += 1
        self.sorted_keys = None

    def ignore_proper_nouns(self):
        words = self.data.keys()
        for word in words:
            if word.lower() != word:
                if word.lower() in self.data:
                    self.data[word.lower()] += self.data[word]
                del self.data[word]
        self.sort()

    def has(self, word):
        return word in self.data

    def get_occurrences(self, word):
        return self.data[word]

    def get_all_occurrences(self):
        return self.occurrences

    def get_words(self):
        return sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word(self) -> (str, int):
        """
        Return random unique word regardless of its frequency.

        :returns word, number of its occurrences in text
        """
        word = random.choice(list(self.data.keys()))
        return word, self.data[word]

    def sort(self):
        self.sorted_keys = sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word_by_frequency(self) -> (str, int):
        """
        Return random word based on its frequency as if you pick up random word
        from the text.

        :returns word, number of its occurrences in text
        """
        number = random.randint(0, self.occurrences)

        if not self.sorted_keys:
            self.sort()

        index = 0
        for word in self.sorted_keys:
            index += self.data[word]
            if index >= number:
                return word, self.data[word]

        return "", 0
