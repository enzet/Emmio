import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from emmio import ui
from emmio.frequency import FrequencyList
from emmio.language import Language, construct_language
from emmio.learning.core import Learning
from emmio.lexicon.core import Lexicon
from emmio.util import MalformedFile

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.ui import error, progress

EXCLUDE_SENTENCES_FILE_NAME: str = "exclude_sentences.json"
EXCLUDE_TRANSLATIONS_FILE_NAME: str = "exclude_translations.json"


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

    exclude_sentences: dict
    exclude_translations: dict[str, list[str]]

    courses: dict = field(default_factory=dict)
    lexicons: dict[Language, Lexicon] = field(default_factory=dict)
    frequency_lists: dict[str, FrequencyList] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, path: Path, user_id: str):
        """
        :param path: path to the user data directory
        :param user_id: unique string user identifier
        """
        with (path / user_id / "exclude_sentences.json").open() as input_file:
            exclude_sentences = json.load(input_file)
        with (
            path / user_id / "exclude_translations.json"
        ).open() as input_file:
            exclude_translations = json.load(input_file)

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
            exclude_sentences,
            exclude_translations,
        )

    def exclude_sentence(self, word: str, sentence_id: int):
        """
        Exclude the sentence from the learning process of the word.

        :param word: word in sentence
        :param sentence_id: sentence unique identifier
        """
        if word not in self.exclude_sentences:
            self.exclude_sentences[word] = []
        self.exclude_sentences[word].append(sentence_id)
        with (self.path / self.id_ / EXCLUDE_SENTENCES_FILE_NAME).open(
            "w+"
        ) as output_file:
            json.dump(self.exclude_sentences, output_file)

    def exclude_translation(self, word: str, other_word: str):
        """
        Exclude some other word from the translation of the word.
        """
        if word not in self.exclude_translations:
            self.exclude_translations[word] = []
        self.exclude_translations[word].append(other_word)
        with (self.path / self.id_ / EXCLUDE_TRANSLATIONS_FILE_NAME).open(
            "w+"
        ) as output_file:
            json.dump(self.exclude_translations, output_file)

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
            except MalformedFile as e:
                error(
                    f"cannot construct frequency list: file {e.path} is "
                    "malformed"
                )
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

    def get_stat(self, interface: ui.Interface):
        sorted_ids: list[str] = sorted(
            self.course_ids,
            key=lambda x: -self.get_course(x).to_repeat(),
        )
        stat: dict[int, int] = defaultdict(int)
        total: int = 0
        for course_id in sorted_ids:
            if not self.get_course(course_id).is_learning:
                continue
            k = self.get_course(course_id).knowledges
            for word in k:
                if k[word].interval.total_seconds() == 0:
                    continue
                depth = k[word].get_depth()
                stat[depth] += 1
                total += 1 / (2**depth)

        rows = []

        total_to_repeat: int = 0
        total_new: int = 0
        total_all: int = 0

        for course_id in sorted_ids:
            learning: Learning = self.get_course(course_id)
            if not learning.is_learning:
                continue
            row = [
                learning.name,
                progress((to_repeat := learning.to_repeat())),
                progress(
                    (new := max(0, learning.ratio - learning.new_today()))
                ),
                str((all_ := learning.learning())),
            ]
            rows.append(row)
            total_to_repeat += to_repeat
            total_new += new
            total_all += all_

        if total_to_repeat or total_new:
            footer = [
                "Total",
                str(total_to_repeat),
                str(total_new),
                str(total_all),
            ]
            rows.append(footer)

        interface.print(f"Pressure: {total:.2f}")
        interface.table(["Course", "Repeat", "Add", "All"], rows)
