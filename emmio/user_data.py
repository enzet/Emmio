import json
from os import listdir
from os.path import join
from typing import Any, Dict, Optional, Set, Iterator

from emmio.language import Language
from emmio.learning import Learning
from emmio.lexicon import Lexicon


class UserData:
    """
    Learning data for one user.
    """
    def __init__(self):
        self.courses = {}
        self.lexicons = {}
        self.path: Optional[str] = None

        self.course_ids: Set[str] = set()

        self.lexicon_config: Dict[str, str] = {}

    @classmethod
    def from_directory(cls, path: str):
        """
        :param path: path to the user data directory
        """
        user_data = cls()

        user_data.path = path

        with open(join(path, "config.json")) as config_file:
            config: Dict[str, Any] = json.load(config_file)
            user_data.id_ = config["id"]
            user_data.name = config["name"]
            user_data.native_languages = set(
                Language(x) for x in config["native_languages"])
            user_data.lexicon_config = config["lexicon"]

        for directory_name in listdir(path):  # type: str
            if directory_name == "learn":
                for file_name in listdir(
                        join(path, directory_name)):  # type: str
                    if file_name.endswith(".json"):
                        user_data.course_ids.add(file_name[:-len(".json")])

        return user_data

    def get_frequency_list_id(self, language: Language) -> str:
        return self.lexicon_config[language.get_code()]

    def get_lexicon_languages(self) -> Iterator[Language]:
        return map(Language, self.lexicon_config.keys())

    def get_lexicon(self, language: Language) -> Lexicon:
        if language not in self.lexicons:
            for file_name in listdir(join(self.path, "lexicon")):  # type: str
                if file_name != f"{language.get_code()}.json":
                    continue
                self.lexicons[language] = Lexicon(
                    language, join(self.path, "lexicon", file_name))
        return self.lexicons[language]

    def get_course(self, course_id: str) -> Learning:
        if course_id not in self.courses:
            for file_name in listdir(join(self.path, "learn")):  # type: str
                if file_name != f"{course_id}.json":
                    continue
                course_id: str = file_name[:-len(".json")]
                self.courses[course_id] = Learning(
                    join(self.path, "learn", file_name), course_id)
        return self.courses[course_id]
