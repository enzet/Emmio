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

    def get_learning(self, learning_id: str) -> Learning:
        return self.learnings[learning_id]

    def get_learning_ids(self) -> Set[str]:
        return set(self.learnings.keys())
