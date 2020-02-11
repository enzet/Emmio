import yaml

from typing import Any, Dict

from emmio import reader


class UserInfo:
    def __init__(self, user_name):
        file_name = user_name + ".yml"

        try:
            structure = reader.read_answers_fast(file_name)
        except Exception:
            structure = yaml.load(open(file_name))

        self.user_name = user_name
        self.learnings = {}

        for learning_id in structure:
            self.learnings[learning_id] = \
                Learning(learning_id, structure[learning_id])

    def get_learning(self, learning_id):
        if learning_id in self.learnings:
            return self.learnings[learning_id]


class Learning:
    def __init__(self, learning_id: str, structure):
        self.id = learning_id
        self.responses = {}
        for word_id in structure:
            self.responses[word_id] = Responses(word_id, structure[word_id])

    def answer(self, word_id: str, is_yes: bool):
        if word_id in self.responses:
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

        self.added = None
        if "added" in structure:
            self.added = structure["added"]

        self.plan = None
        if "plan" in structure:
            self.plan = structure["plan"]

        self.last = None
        if "last" in structure:
            self.last = structure["last"]

    def answer(self, is_yes):
        shortcut = "y" if is_yes else "n"
        self.answers += shortcut

    def is_learned(self):
        return self.answers[-3:] == "yyy" or self.answers == "y" or \
            (not self.answers and self.plan >= 1000000000)


class Answers:
    def __init__(self, file_name: str):
        self.answers: Dict[str, Dict[str, Dict[str, Any]]] = {}
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
                    {"last": int(line[line.find("last: 2") + 6:line.find(", plan")]),
                     "plan": int(line[line.find("plan: ", 10) + 6:line.find("}")])}

                answers_position = line.find("answers:")
                if answers_position != -1:
                    element["answers"] = \
                        line[answers_position + 9:line.find(",", answers_position)]

                added_position = line.find("added:")
                if added_position != -1:
                    element["added"] = \
                        int(line[added_position + 7:line.find(",", added_position)])

                key = line[2:line.find(":")]

                if key[0] == '"':
                    key = key[1:-1]

                self.answers[dictionary_name][key] = element


