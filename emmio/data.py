import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio import ui
from emmio.dictionary.core import Dictionary, Dictionaries
from emmio.dictionary.data import DictionaryData
from emmio.language import Language, construct_language
from emmio.learn.core import Learning
from emmio.lists.core import List
from emmio.lists.data import ListsData
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.core import SentencesCollection, Sentences
from emmio.sentence.data import SentencesData
from emmio.ui import progress
from emmio.user.data import UserData

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

EXCLUDE_SENTENCES_FILE_NAME: str = "exclude_sentences.json"
EXCLUDE_TRANSLATIONS_FILE_NAME: str = "exclude_translations.json"


@dataclass
class Data:
    """Registry of all available Emmio data."""

    lists: ListsData
    sentences: SentencesData
    dictionaries: DictionaryData
    user_data: dict[str, UserData]

    @classmethod
    def from_directory(cls, path: Path) -> "Data":

        lists: ListsData = ListsData.from_config(path / "lists")
        sentences: SentencesData = SentencesData.from_config(path / "sentences")
        dictionaries: DictionaryData = DictionaryData.from_config(
            path / "dictionaries"
        )

        users_path: Path = path / "users"
        user_data: dict[str, UserData] = {}

        for user_path in users_path.iterdir():
            with (user_path / "config.json").open() as user_config_file:
                config: dict = json.load(user_config_file)
                user_data[user_path.name] = UserData.from_config(
                    user_path, config
                )

        return cls(lists, sentences, dictionaries, user_data)

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
        return self.get_frequency_list(
            self.user_data[user_id].get_lexicon[language.get_code()]
        )

    def get_lexicon_languages(self) -> Iterator[Language]:
        return map(construct_language, self.lexicon_config.keys())

    def get_list(self, id_) -> List | None:
        return self.lists.get_list(id_)

    def get_frequency_list(self, id_: str) -> FrequencyList | None:
        return self.lists.get_frequency_list(id_)

    def get_dictionary(self, usage_config: dict) -> Dictionary:
        return self.dictionaries.get_dictionary(usage_config)

    def get_dictionaries(self, usage_configs: list[dict]) -> Dictionaries:
        return self.dictionaries.get_dictionaries(usage_configs)

    def get_sentences(self, usage_config: dict) -> Sentences:
        return self.sentences.get_sentences(usage_config)

    def get_sentences_collection(
        self, usage_configs: list[dict]
    ) -> SentencesCollection:
        return self.sentences.get_sentences_collection(usage_configs)

    def get_words(self, list_id: str):
        return self.get_list(list_id).get_words()

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

    def get_stat(self, interface: ui.Interface, user_data: UserData):

        sorted_ids: list[str] = sorted(
            user_data.learnings,
            key=lambda x: -self.get_course(x).to_repeat(),
        )
        stat: dict[int, int] = defaultdict(int)
        total: int = 0
        for course_id in sorted_ids:
            if not self.get_course(course_id).is_learning:
                continue
            k = self.get_course(course_id).knowledge
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
