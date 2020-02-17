import random
import yaml

from typing import Any, Dict, List, Optional, Set

from emmio import reader


class Learning:
    def __init__(self, learning_id: str, responses: Dict[str, "Responses"]):
        self.id: str = learning_id
        self.responses: Dict[str, "Responses"] = responses

    def answer(self, question_id: str, is_yes: bool, time: int):
        if question_id not in self.responses:  # type: str
            self.responses[question_id] = Responses(question_id, {})
        self.responses[question_id].answer(is_yes, time)

    def has(self, word_id: str) -> bool:
        return word_id in self.responses

    def is_learned(self, word_id: str) -> bool:
        if word_id not in self.responses:
            return False
        return self.responses[word_id].is_learned()

    def get_question_ids(self) -> Set[str]:
        return set(self.responses.keys())

    def get_responses(self, question_id: str) -> "Responses":
        return self.responses[question_id]

    def to_string(self):
        obj = ""
        obj += self.id + ':\n'
        for question_id in self.responses:  # type: str
            responses: Responses = self.responses[question_id]
            if question_id in ['on', 'off', 'yes', 'no', 'null', 'true',
                    'false']:
                obj += "  '" + question_id + "': {"
            else:
                obj += '  ' + question_id + ': {'
            obj += responses.to_string()
            obj = obj[:-2]
            obj += '}\n'
        return obj


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

    def answer(self, is_yes: bool, time: int):
        shortcut: str = "y" if is_yes else "n"
        self.answers += shortcut

        if self.plan is None:
            if is_yes:
                self.plan = 1000000000
            else:
                self.plan = time + 2 + int(6 * random.random())
        else:
            diff = self.plan - self.last
            if is_yes:
                if diff < 8:
                    diff = 8 + int(8 * random.random())
                elif diff < 16:
                    diff = 16 + int((60 * 24 - 16) * random.random())
                elif diff < 60 * 24:
                    diff = 60 * 24 + int(60 * 24 * random.random())
                else:
                    diff = int(diff * (2.0 + random.random()))
            else:
                diff = 2 + int(6 * random.random())
            self.plan = time + diff
        self.last = time

    def is_learned(self):
        return self.answers[-3:] == "yyy" or self.answers == "y" or \
               (not self.answers and self.plan >= 1000000000)

    def to_string(self) -> str:
        obj = ""
        if self.added is not None:
            obj += f"added: {self.added}"
        if self.answers is not None:
            obj += f"answers: {self.answers}"
        if self.last is not None:
            obj += f"last: {self.last}"
        if self.plan is not None:
            obj += f"plan: {self.plan}"
        if obj:
            obj = obj[:-2]
        return obj


class FullUserData:
    def __init__(self, file_name: str):
        self.learnings: Dict[str, Learning] = {}
        input_file = open(file_name)
        line = None
        dictionary_name = None
        ll: Dict[str, Responses] = {}
        while line != "":
            line = input_file.readline()
            if line == "":
                break
            if line[0] != " ":
                if ll is not None:
                    self.learnings[dictionary_name] = \
                        Learning(dictionary_name, ll)
                dictionary_name = line[:-2]
                ll = {}
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

                ll[key] = Responses(key, element)

    def write(self, user_file_name: str):
        obj = ""

        for learning in self.learnings:  # type: Learning
            obj += learning.to_string()

        open(user_file_name, 'w+').write(obj)

    def get_learning(self, learning_id: str) -> Learning:
        return self.learnings[learning_id]

    def get_learning_ids(self) -> Set[str]:
        return set(self.learnings.keys())
