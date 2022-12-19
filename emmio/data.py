import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio import ui
from emmio.audio.data import AudioData
from emmio.dictionary.core import Dictionary, DictionaryCollection
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

DICTIONARIES_DIRECTORY_NAME: str = "dictionaries"
SENTENCES_DIRECTORY_NAME: str = "sentences"
LISTS_DIRECTORY_NAME: str = "lists"
AUDIO_DIRECTORY_NAME: str = "audio"
USERS_DIRECTORY_NAME: str = "users"
CONFIGURATION_FILE_NAME: str = "config.json"


@dataclass
class Data:
    """
    Registry of all available Emmio data.

    This class manages Emmio data directory which is by default located in
    ``~/.emmio``.  It expects to find directories ``lists``, ``sentences``,
    ``dictionaries``, ``audio`` with artifacts and directory ``users`` with
    user data.
    """

    lists: ListsData
    sentences: SentencesData
    dictionaries: DictionaryData
    audio: AudioData
    users_data: dict[str, UserData]

    @classmethod
    def from_directory(cls, path: Path) -> "Data":

        lists: ListsData = ListsData.from_config(path / LISTS_DIRECTORY_NAME)
        sentences: SentencesData = SentencesData.from_config(
            path / SENTENCES_DIRECTORY_NAME
        )
        dictionaries: DictionaryData = DictionaryData.from_config(
            path / DICTIONARIES_DIRECTORY_NAME
        )
        audio: AudioData = AudioData.from_config(path / AUDIO_DIRECTORY_NAME)

        users_path: Path = path / USERS_DIRECTORY_NAME
        user_data: dict[str, UserData] = {}

        for user_path in users_path.iterdir():
            with (
                user_path / CONFIGURATION_FILE_NAME
            ).open() as user_config_file:
                user_data[user_path.name] = UserData.from_config(
                    user_path, json.load(user_config_file)
                )
        return cls(lists, sentences, dictionaries, audio, user_data)

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
            self.users_data[user_id].get_lexicon[language.get_code()]
        )

    def get_lexicon_languages(self) -> Iterator[Language]:
        return map(construct_language, self.lexicon_config.keys())

    def get_list(self, id_) -> List | None:
        return self.lists.get_list(id_)

    def get_frequency_list(self, id_: str) -> FrequencyList | None:
        return self.lists.get_frequency_list(id_)

    def get_dictionary(self, usage_config: dict) -> Dictionary:
        return self.dictionaries.get_dictionary(usage_config)

    def get_dictionaries(
        self, usage_configs: list[dict]
    ) -> DictionaryCollection:
        return self.dictionaries.get_dictionaries(usage_configs)

    def get_sentences(self, usage_config: dict) -> Sentences:
        return self.sentences.get_sentences(usage_config)

    def get_sentences_collection(
        self, usage_configs: list[dict]
    ) -> SentencesCollection:
        return self.sentences.get_sentences_collection(usage_configs)

    def get_audio_provider(self, usage_config: dict):
        return self.audio.get_audio_provider(usage_config)

    def get_audio_collection(self, usage_configs: list[dict]):
        return self.audio.get_audio_collection(usage_configs)

    def get_words(self, id_: str) -> list[str]:
        return self.get_list(id_).get_words()

    def get_learning(self, user_id: str, learning_id: str) -> Learning:
        return self.users_data[user_id].get_learning(learning_id)

    def get_active_learnings(self, user_id: str):
        return self.users_data[user_id].get_active_learnings()

    def get_stat(self, interface: ui.Interface, user_id: str):

        learnings: list[Learning] = sorted(
            self.get_active_learnings(user_id),
            key=lambda x: x.count_questions_to_repeat(),
        )
        stat: dict[int, int] = defaultdict(int)
        total: int = 0
        for learning in learnings:
            k = learning.knowledge
            for word in k:
                if k[word].interval.total_seconds() == 0:
                    continue
                depth = k[word].get_depth()
                stat[depth] += 1
                total += 1 / (2**depth)

        rows = [
            [
                learning.config.name,
                learning.count_questions_to_repeat(),
                max(
                    0,
                    learning.config.max_for_day
                    - learning.count_questions_added_today(),
                ),
                len(learning.process.skipping),
                learning.count_questions_to_learn(),
            ]
            for learning in learnings
        ]
        footer: list[str] = ["Total"] + [
            str(sum(x[i] for x in rows)) for i in (1, 2, 3, 4)
        ]
        for row in rows:
            for i in 1, 2, 3:
                row[i] = progress(row[i])
            row[4] = str(row[4])

        rows.append(footer)

        interface.print(f"Pressure: {total:.2f}")
        interface.table(["Course", "Repeat", "Add", "Skipping", "All"], rows)
