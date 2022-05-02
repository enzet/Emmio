import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from emmio.language import Language, construct_language
from emmio.learning import Learning
from emmio.frequency import FrequencyList, MalformedFile
from emmio.lexicon import Lexicon

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.ui import error


@dataclass
class UserData:
    """
    Learning data for one user.
    """

    id_: str
    name: str
    path: Path
    native_languages: set[Language]
    course_ids: set[str]

    lexicon_config: dict[str, str]
    frequency_list_config: dict[str, dict[str, str]]
    learn_config: dict[str, dict[str, str]]

    courses: dict = field(default_factory=dict)
    lexicons: dict[Language, Lexicon] = field(default_factory=dict)
    frequency_lists: dict[str, FrequencyList] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, path: Path, user_id: str):
        """
        :param path: path to the user data directory
        :param user_id: unique string user identifier
        """
        with (path / user_id / "config.json").open() as config_file:
            config: dict[str, Any] = json.load(config_file)

            return cls(
                user_id,
                config["name"],
                path,
                set(construct_language(x) for x in config["native_languages"]),
                set(config["learn"].keys()),
                config["lexicon"],
                config["priority"],
                config["learn"],
            )

    def get_frequency_list_for_lexicon(
        self, language: Language
    ) -> FrequencyList:
        return self.get_frequency_list(self.lexicon_config[language.get_code()])

    def get_frequency_list_structure(
        self, frequency_list_id: str
    ) -> dict[str, str]:
        return self.frequency_list_config[frequency_list_id]

    def get_frequency_list(
        self, frequency_list_id: str
    ) -> Optional[FrequencyList]:
        if frequency_list_id not in self.frequency_lists:
            try:
                frequency_list: FrequencyList = FrequencyList.from_structure(
                    self.frequency_list_config[frequency_list_id],
                    self.path / "priority",
                )
                self.frequency_lists[frequency_list_id] = frequency_list
            except MalformedFile:
                error("cannot construct frequency list")
                return None

        return self.frequency_lists[frequency_list_id]

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
            file_path: Path = (
                self.path / self.id_ / "learn" / f"{course_id}.json"
            )
            if file_path.is_file():
                course_id: str = file_path.name[: -len(".json")]
                config = self.learn_config[course_id]
                self.courses[course_id] = Learning(file_path, config, course_id)

        return self.courses[course_id]
