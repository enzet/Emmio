from engine import reader


class Dictionary:
    """
    Dictionary.
    """
    def __init__(self, file_name: str=None, format: str=None):
        if file_name:
            self.file_name = file_name
            self.dictionary = reader.read_dict(file_name, format)
        else:
            self.file_name = None
            self.dictionary = {}

    def join(self, file_name: str, format: str):
        new_dictionary = reader.read_dict(file_name, format)
        for key in new_dictionary:
            if key not in self.dictionary:
                self.dictionary[key] = new_dictionary[key]

    def add(self, word: str, definition: str):
        self.dictionary[word] = definition

    def set_file_name(self, file_name: str):
        self.file_name = file_name

    def write(self):
        output = open(self.file_name, 'w+')
        for word in sorted(self.dictionary):
            output.write(word + '\n')
            output.write("    " + self.dictionary[word] + "\n")

    def has(self, word: str):
        return word in self.dictionary

    def get(self, word: str):
        return self.dictionary[word]
