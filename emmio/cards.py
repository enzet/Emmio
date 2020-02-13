import json

from typing import Any, Dict, List

from emmio.dictionary import SimpleDictionary


class Cards:
    def __init__(self, file_name: str, file_format: str = "dict"):
        """
        Construct dictionary with key and values as Unicode strings.

        :param file_name: dictionary file name.
        :param file_format: dictionary file format (dict or yaml).

        :return parsed dictionary as Python dict structure.
        """
        if file_format == "dict":
            self.cards: Dict[str, str] = \
                SimpleDictionary(file_name, file_format).to_structure()
        elif file_format == "json":
            self.cards: Dict[str, Any] = json.load(open(file_name, "r"))

    def has(self, question: str) -> bool:
        return question in self.cards

    def get_questions(self) -> List[str]:
        return list(self.cards.keys())

    def get_answer(self, question: str) -> str:
        return self.cards.get(question)

    def get_answer_key(self, question: str, key: str) -> str:
        return self.cards.get(question)[key]