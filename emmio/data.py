"""Manager for all Emmio data artifacts.

This class manages Emmio data directory which is by default located in
`~/.emmio`. It expects to find directories
  - `lists`,
  - `sentences`,
  - `dictionaries`,
  - `audio`,
  - `texts`,
with artifacts and directory `users` with user data.
"""

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio import ui
from emmio.audio.core import AudioCollection, AudioProvider
from emmio.audio.data import AudioData
from emmio.dictionary.core import Dictionary, DictionaryCollection
from emmio.dictionary.data import DictionaryData
from emmio.language import Language
from emmio.learn.core import Learning
from emmio.lexicon.core import Lexicon
from emmio.lists.core import List
from emmio.lists.data import ListsData
from emmio.lists.frequency_list import FrequencyList
from emmio.sentence.core import Sentences, SentencesCollection
from emmio.sentence.data import SentencesData
from emmio.text.core import Texts
from emmio.text.data import TextData
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
TEXTS_DIRECTORY_NAME: str = "texts"
USERS_DIRECTORY_NAME: str = "users"
CONFIGURATION_FILE_NAME: str = "config.json"


@dataclass
class Data:
    """Registry of all available Emmio data.

    This class manages Emmio data directory which is by default located in
    `~/.emmio`.  It expects to find directories `lists`, `sentences`,
    `dictionaries`, `audio`, and `texts` with artifacts and directory `users`
    with user data.
    """

    path: Path
    """Managed directory."""

    _lists_data: ListsData | None
    """Manager for frequency and word lists."""

    sentences: SentencesData
    """Manager for sentences with translations."""

    dictionaries: DictionaryData
    """Manager for dictionaries."""

    _audio_data: AudioData | None
    """Manager for audio files with pronunciation."""

    texts: TextData
    """Manager for texts and translations."""

    users_data: dict[str, UserData]
    """Mapping from used unique identifiers to user data managers."""

    @classmethod
    def from_directory(cls, path: Path) -> Self:
        """Initialize Emmio data from its directory.

        :param path: path to the directory with Emmio data
        """
        sentences: SentencesData = SentencesData.from_config(
            path / SENTENCES_DIRECTORY_NAME
        )
        dictionaries: DictionaryData = DictionaryData.from_config(
            path / DICTIONARIES_DIRECTORY_NAME
        )
        texts: TextData = TextData.from_config(path / TEXTS_DIRECTORY_NAME)

        users_path: Path = path / USERS_DIRECTORY_NAME
        user_data: dict[str, UserData] = {}

        if not users_path.exists():
            users_path.mkdir()

        for user_path in users_path.iterdir():
            with (user_path / CONFIGURATION_FILE_NAME).open(
                encoding="utf-8"
            ) as user_config_file:
                user_data[user_path.name] = UserData.from_config(
                    user_path.name, user_path, json.load(user_config_file)
                )
        return cls(path, None, sentences, dictionaries, None, texts, user_data)

    def get_lists_data(self) -> ListsData:
        """Get frequency and word lists data."""
        if not self._lists_data:
            logging.info("Loading list data...")
            self._lists_data = ListsData.from_config(
                self.path / LISTS_DIRECTORY_NAME
            )
        return self._lists_data

    def get_list(self, usage_config: dict) -> List | None:
        """Get a list by usage configuration."""
        return self.get_lists_data().get_list(usage_config)

    def get_frequency_list(self, usage_config: dict) -> FrequencyList | None:
        """Get a frequency list by usage configuration."""
        return self.get_lists_data().get_frequency_list(usage_config)

    def get_dictionary(self, usage_config: dict) -> Dictionary | None:
        """Get a dictionary by usage configuration."""
        return self.dictionaries.get_dictionary(usage_config)

    def get_dictionaries(
        self, usage_configs: list[dict]
    ) -> DictionaryCollection:
        """Get a collection of dictionaries by usage configurations."""
        return self.dictionaries.get_dictionaries(usage_configs)

    def get_sentences(self, usage_config: dict) -> Sentences:
        """Get sentences by usage configuration."""
        return self.sentences.get_sentences(usage_config)

    def get_text(self, text_id: str) -> Texts:
        """Get a text by its identifier."""
        return self.texts.get_text(text_id)

    def get_sentences_collection(
        self, usage_configs: list[dict]
    ) -> SentencesCollection:
        """Get a collection of sentences by usage configurations."""
        return self.sentences.get_sentences_collection(usage_configs)

    def get_audio_data(self) -> AudioData:
        """Get audio data."""

        if not self._audio_data:
            logging.info("Loading audio data...")
            self._audio_data = AudioData.from_config(
                self.path / AUDIO_DIRECTORY_NAME
            )
        return self._audio_data

    def get_audio_provider(self, usage_config: dict) -> AudioProvider:
        """Get an audio provider by usage configuration."""
        return self.get_audio_data().get_audio_provider(usage_config)

    def get_audio_collection(
        self, usage_configs: list[dict]
    ) -> AudioCollection:
        """Get an audio collection by usage configurations."""
        return self.get_audio_data().get_audio_collection(usage_configs)

    def get_words(self, id_: str) -> list[str] | None:
        """Get words from a list by its identifier."""

        if not (list_ := self.get_list({"id": id_})):
            return None
        return list_.get_words()

    def get_learning(self, user_id: str, id_: str) -> Learning:
        """Get a learning by its identifier."""
        return self.users_data[user_id].get_learning(id_)

    def get_learnings(self, user_id: str) -> Iterator[Learning]:
        """Get all learnings for a user."""
        return self.users_data[user_id].get_all_learnings()

    def get_active_learnings(self, user_id: str) -> Iterator[Learning]:
        """Get all active learnings for a user."""
        return self.users_data[user_id].get_active_learnings()

    def get_lexicons(
        self, user_id: str, languages: list[Language] | None = None
    ) -> list[Lexicon]:
        """Get lexicons for a user."""
        return self.users_data[user_id].get_lexicons(languages)

    def print_learning_statistics(
        self, interface: ui.Interface, user_id: str
    ) -> None:
        """Print learning statistics."""

        learnings: list[Learning] = sorted(
            self.get_active_learnings(user_id),
            key=lambda x: -x.count_questions_to_repeat(),
        )
        rows: list[list[str | int]] = [
            [
                learning.config.name,
                learning.count_questions_to_repeat(),
                learning.count_questions_to_add(),
                learning.count_questions_to_learn(),
            ]
            for learning in learnings
        ]
        footer: list[str | int] = ["Total"] + [
            sum(int(x[i]) for x in rows) for i in range(1, 4)
        ]
        for row in rows:
            for i in range(1, 3):
                row[i] = progress(int(row[i]))
            row[3] = str(row[3])

        rows.append(footer)

        user_data: UserData = self.users_data[user_id]

        pressure: float = user_data.get_learn_data().compute_pressure()
        postponed: float = user_data.get_learn_data().count_postponed()

        interface.print(f"Pressure: {pressure:.2f}")
        interface.print(f"Postponed: {postponed}")

    def has_user(self, user_id: str) -> bool:
        """Check whether the user exists."""
        return user_id in self.users_data

    def create_user(self, user_id: str, user_name: str) -> None:
        """Create new user."""

        path: Path = self.path / USERS_DIRECTORY_NAME / user_id
        path.mkdir()
        self.users_data[user_id] = UserData.create(path, user_id, user_name)

    def get_frequency_lexicons(
        self, user_id: str, languages: list[Language] | None = None
    ) -> dict[Language, list[Lexicon]]:
        """Get frequency lexicons for a user."""
        return self.users_data[user_id].get_frequency_lexicons(languages)
