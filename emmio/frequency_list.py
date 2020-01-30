import json
import random
import yaml

from emmio import ui


class WordOccurrences:
    def __init__(self, word: str, occurrences: int):
        self.word = word
        self.occurrences = occurrences


class FrequencyList:
    """
    Frequency list of some text.
    """
    def __init__(self) -> None:
        self.data = {}
        self.occurrences = 0
        self.sorted_keys = None

    def __len__(self) -> int:
        return len(self.data)

    def read(self, file_name: str, file_format: str) -> None:
        if file_format == "yaml":
            self.read_yaml(file_name)
        elif file_format == "text":
            self.read_list(file_name)
        elif file_format == "json":
            self.read_json(file_name)
        else:
            raise Exception("unknown file format")

    def read_yaml(self, file_name: str) -> None:
        """
        Read file with frequency in the format:
        `<word>: <number of occurrences>`.

        :param file_name: input YAML file name
        """
        ui.write("Reading YAML frequency list from " + file_name + "...")

        try:
            self.read_list(file_name, ": ")
        except Exception:
            structure = yaml.load(open(file_name, "r"))

            for word in structure:
                self.data[word] = structure[word]

        self.sort()

    def read_json(self, file_name: str) -> None:
        """
        Read file with frequency in the JSON format:
        `[["<word>", <number of occurrences>], ...]`.

        :param file_name: input JSON file name
        """
        ui.write("Reading JSON frequency list from " + file_name + "...")

        structure = json.load(open(file_name, "r"))

        for word, occurrences in structure:
            self.data[word] = int(occurrences)
            self.occurrences += occurrences

        self.sort()

    def read_list(self, file_name: str, delimiter: str = " ") -> None:
        """
        Read file with frequency in the format:
        `<word><delimiter><number of occurrences>`.

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

    def write_json(self, file_name: str) -> None:
        structure = []
        for word in sorted(self.data.keys(), key=lambda x: -self.data[x]):
            structure.append([word, self.data[word]])
        with open(file_name, 'w+') as output:
            json.dump(structure, output, indent=4, ensure_ascii=False)

    def add(self, word) -> None:
        if word in self.data:
            self.data[word] += 1
        else:
            self.data[word] = 1

        self.occurrences += 1
        self.sorted_keys = None

    def ignore_proper_nouns(self) -> None:
        words = self.data.keys()
        for word in words:
            if word.lower() != word:
                if word.lower() in self.data:
                    self.data[word.lower()] += self.data[word]
                del self.data[word]
        self.sort()

    def has(self, word) -> bool:
        return word in self.data

    def get_occurrences(self, word: str) -> int:
        return self.data[word]

    def get_all_occurrences(self) -> int:
        return self.occurrences

    def get_words(self):
        return sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word(self) -> (str, int):
        """
        Return random unique word regardless of its frequency.

        :return word, number of its occurrences in text
        """
        word = random.choice(list(self.data.keys()))
        return word, self.data[word]

    def sort(self) -> None:
        self.sorted_keys = sorted(self.data.keys(), key=lambda x: -self.data[x])

    def get_random_word_by_frequency(self) -> (str, int):
        """
        Return random word based on its frequency as if you pick up random word
        from the text.

        :return word, number of its occurrences in text
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
