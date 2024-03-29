import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio import ui
from emmio.audio.data import AudioData
from emmio.dictionary.core import Dictionary, DictionaryCollection
from emmio.dictionary.data import DictionaryData
from emmio.language import Language
from emmio.learn.core import Learning
from emmio.lexicon.core import Lexicon
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
    """Manager for frequency and word lists."""

    sentences: SentencesData
    """Manager for sentences with translations."""

    dictionaries: DictionaryData
    """Manager for dictionaries."""

    audio: AudioData
    """Manager for audio files with pronunciation."""

    users_data: dict[str, UserData]
    """Mapping from used unique identifiers to user data managers."""

    @classmethod
    def from_directory(cls, path: Path) -> "Data":
        """Initialize Emmio data from its directory."""

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
        """Exclude some other word from the translation of the word."""
        if word not in self.exclude_translations:
            self.exclude_translations[word] = []
        self.exclude_translations[word].append(other_word)
        with (self.path / self.id_ / EXCLUDE_TRANSLATIONS_FILE_NAME).open(
            "w+"
        ) as output_file:
            json.dump(self.exclude_translations, output_file)

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

    def get_learning(self, user_id: str, id_: str) -> Learning:
        return self.users_data[user_id].get_learning(id_)

    def get_active_learnings(self, user_id: str) -> Iterator[Learning]:
        return self.users_data[user_id].get_active_learnings()

    def get_lexicon(self, user_id: str, language: Language) -> Lexicon:
        return self.users_data[user_id].get_lexicon(language)

    def get_lexicons(self, user_id: str) -> Iterator[Lexicon]:
        return self.users_data[user_id].get_lexicons()

    def print_learning_statistics(
        self, interface: ui.Interface, user_id: str
    ) -> None:
        learnings: list[Learning] = sorted(
            self.get_active_learnings(user_id),
            key=lambda x: -x.count_questions_to_repeat(),
        )
        rows: list[list[str | int]] = [
            [
                learning.config.name,
                learning.count_questions_to_repeat(),
                learning.count_questions_to_add(),
                len(learning.process.skipping),
                learning.count_questions_to_learn(),
            ]
            for learning in learnings
        ]
        footer: list[str] = ["Total"] + [
            str(sum(x[i] for x in rows)) for i in range(1, 5)
        ]
        for row in rows:
            for i in range(1, 4):
                row[i] = progress(row[i])
            row[4] = str(row[4])

        rows.append(footer)

        pressure: float = self.users_data[user_id].learnings.compute_pressure()
        interface.print(f"Pressure: {pressure:.2f}")
        interface.table(["Course", "Repeat", "Add", "Skipping", "All"], rows)
