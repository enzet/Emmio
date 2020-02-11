import yaml

from typing import Any, Dict, Optional

from emmio import reader


class UserInfo:
    def __init__(self, user_name):
        file_name = user_name + ".yml"

        answers = FullUserData(file_name)

        self.user_name: str = user_name
        self.learnings = {}

        for learning_id in answers.get_answers():  # type: str
            self.learnings[learning_id] = \
                Learning(learning_id, answers.get_answers()[learning_id])

    def get_learning(self, learning_id):
        if learning_id in self.learnings:
            return self.learnings[learning_id]


class Learning:
    def __init__(self, learning_id: str, responses: Dict[str, "Responses"]):
        self.id: str = learning_id
        self.responses: Dict[str, "Responses"] = responses

    def answer(self, word_id: str, is_yes: bool):
        if word_id in self.responses:  # type: str
            self.responses[word_id].answer(is_yes)

    def has(self, word_id: str) -> bool:
        return word_id in self.responses

    def is_learned(self, word_id: str) -> bool:
        if word_id not in self.responses:
            return False
        return self.responses[word_id].is_learned()


class Responses:
    def __init__(self, word_id: str, structure: Dict[str, Any]):
        self.id: str = word_id

        self.answers: str = ""
        if "answers" in structure:
            self.answers = structure["answers"]

        self.added: Optional[int] = None
        if "added" in structure:
            self.added = structure["added"]

        self.plan: Optional[int] = None
        if "plan" in structure:
            self.plan = structure["plan"]

        self.last: Optional[int] = None
        if "last" in structure:
            self.last = structure["last"]

    def answer(self, is_yes: bool):
        shortcut: str = "y" if is_yes else "n"
        self.answers += shortcut

    def is_learned(self):
        return self.answers[-3:] == "yyy" or self.answers == "y" or \
            (not self.answers and self.plan >= 1000000000)


class FullUserData:
    def __init__(self, file_name: str):
        self.answers: Dict[str, Dict[str, Responses]] = {}
        input_file = open(file_name)
        line = None
        dictionary_name = None
        while line != "":
            line = input_file.readline()
            if line == "":
                break
            if line[0] != " ":
                dictionary_name = line[:-2]
                self.answers[dictionary_name] = {}
            else:
                element: Dict[str, Any] = \
                    {"last": int(line[line.find("last: 2") + 6:
                        line.find(", plan")]),
                     "plan": int(line[line.find("plan: ", 10) + 6:
                        line.find("}")])}

                answers_position = line.find("answers:")
                if answers_position != -1:
                    element["answers"] = \
                        line[answers_position + 9:
                            line.find(",", answers_position)]

                added_position = line.find("added:")
                if added_position != -1:
                    element["added"] = \
                        int(line[added_position + 7:
                            line.find(",", added_position)])

                key = line[2:line.find(":")]

                if key[0] == '"':
                    key = key[1:-1]

                self.answers[dictionary_name][key] = Responses(key, element)

    def get_answers(self) -> Dict[str, Dict[str, Responses]]:
        return self.answers
