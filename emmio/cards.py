from typing import List

from emmio.dictionary import Dictionary


class Cards:
    def __init__(self, file_name: str, file_format: str = 'dict'):
        """
        Construct dictionary with key and values as Unicode strings.

        :param file_name: dictionary file name.
        :param file_format: dictionary file format (dict or yaml).

        :return parsed dictionary as Python dict structure.
        """
        self.dictionary = Dictionary(file_name, file_format)

    def has(self, question: str) -> bool:
        return question in self.dictionary

    def get_questions(self) -> List[str]:
        return self.dictionary.get_keys()

    def get_answer(self, question: str) -> str:
        return self.dictionary.get(question)

    def get_answer_key(self, question: str, key: str) -> str:
        return self.dictionary.get(question)[key]