import json
from os import listdir
from os.path import join
from typing import Dict, Set, Any

from emmio.language import Language
from emmio.learning import Learning
from emmio.lexicon import Lexicon
from emmio.ui import log


class UserData:
    """
    Learning data for one user.
    """
    def __init__(self):
        self.courses = {}
        self.lexicons = {}

    @classmethod
    def from_directory(cls, path: str):
        """
        :param path: path to the user data directory
        """
        user_data = cls()

        user_data.path: str = path

        with open(join(path, "config.json")) as config_file:
            config: Dict[str, Any] = json.load(config_file)
            user_data.id_: str = config["id"]
            user_data.name: str = config["name"]
            user_data.native_languages: Set[Language] = set(
                Language(x) for x in config["native_languages"])

        for directory_name in listdir(path):  # type: str
            if directory_name == "lexicon":
                for file_name in listdir(
                        join(path, directory_name)):  # type: str
                    if not file_name.endswith(".json"):
                        continue
                    language: str = file_name[:-len(".json")]
                    lexicon: Lexicon = Lexicon(
                        language, join(path, directory_name, file_name))
                    user_data.lexicons[lexicon.language.get_code()] = lexicon
            if directory_name == "learn":
                for file_name in listdir(
                        join(path, directory_name)):  # type: str
                    if not file_name.endswith(".json"):
                        continue
                    course_id: str = file_name[:-len(".json")]
                    log(f"reading {file_name}")
                    user_data.courses[course_id] = Learning(
                        join(path, directory_name, file_name), course_id)

        return user_data

    def get_lexicons(self) -> Dict[str, Lexicon]:
        return self.lexicons

    def get_courses(self) -> Dict[str, Learning]:
        return self.courses
