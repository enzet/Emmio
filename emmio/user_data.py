import json
from os import listdir
from os.path import join
from typing import Any, Iterator, Optional

from emmio.language import Language, construct_language
from emmio.learning import Learning
from emmio.lexicon import Lexicon

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class UserData:
    """
    Learning data for one user.
    """

    def __init__(self):
        self.courses = {}
        self.lexicons = {}
        self.path: Optional[str] = None

        self.course_ids: set[str] = set()

        self.lexicon_config: dict[str, str] = {}

    @classmethod
    def from_directory(cls, path: str):
        """
        :param path: path to the user data directory
        """
        user_data: "UserData" = cls()

        user_data.path = path

        with open(join(path, "config.json")) as config_file:
            config: dict[str, Any] = json.load(config_file)
            user_data.id_ = config["id"]
            user_data.name = config["name"]
            user_data.native_languages = set(
                construct_language(x) for x in config["native_languages"]
            )
            user_data.lexicon_config = config["lexicon"]

        for directory_name in listdir(path):  # type: str
            if directory_name == "learn":
                for file_name in listdir(
                    join(path, directory_name)
                ):  # type: str
                    if file_name.endswith(".json"):
                        user_data.course_ids.add(file_name[: -len(".json")])

        return user_data

    def get_frequency_list_id(self, language: Language) -> str:
        return self.lexicon_config[language.get_code()]

    def get_lexicon_languages(self) -> Iterator[Language]:
        return map(construct_language, self.lexicon_config.keys())

    def get_lexicon(self, language: Language) -> Lexicon:
        if language not in self.lexicons:
            file_path: Path = (
                self.path / self.id_ / "lexicon" / f"{language.get_code()}.json"
            )
            if file_path.is_file():
                self.lexicons[language] = Lexicon(language, file_path)

        return self.lexicons[language]

    def get_course(self, course_id: str) -> Learning:
        if course_id not in self.courses:
            file_path: Path = self.path / self.id_ / "learn" / f"{course_id}.json"
            if file_path.is_file():
                course_id: str = file_path.name[: -len(".json")]
                config = self.learn_config[course_id]
                self.courses[course_id] = Learning(file_path, config, course_id)

        return self.courses[course_id]
