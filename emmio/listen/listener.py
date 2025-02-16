import logging
from pathlib import Path
from time import sleep

try:
    import mpv
except (OSError, ImportError):
    logging.warning("MPV is not installed, audio playback will be disabled.")
    mpv = None

from emmio.audio.core import AudioCollection
from emmio.data import Data
from emmio.dictionary.core import DictionaryCollection
from emmio.language import Language
from emmio.learn.core import Learning
from emmio.learn.teacher import Teacher
from emmio.listen.config import ListenConfig
from emmio.listen.core import Listening, PAUSE_AFTER_PLAY
from emmio.lists.frequency_list import FrequencyList
from emmio.ui import RichInterface
from emmio.user.data import UserData


class Listener:
    def __init__(
        self, listening: Listening, data: Data, user_data: UserData
    ) -> None:
        self.data: Data = data
        self.user_data: UserData = user_data
        self.listening: Listening = listening
        self.player = mpv.MPV() if mpv else None

        listen_config: ListenConfig = self.listening.config

        self.base_language: Language = Language.from_code(
            listen_config.base_language
        )
        self.learning: Learning = self.user_data.get_learning(
            listen_config.learning_id
        )
        self.base_audio_collection: AudioCollection = (
            self.data.get_audio_collection(listen_config.audio_base)
        )
        self.learning_audio_collection: AudioCollection = (
            self.data.get_audio_collection(listen_config.audio_learning)
        )
        self.dictionary_collection: DictionaryCollection = (
            self.data.get_dictionaries(listen_config.dictionaries)
        )
        self.safe_question_ids: list[str] = (
            self.learning.get_safe_question_ids()
        )

        self.teacher = Teacher(
            RichInterface(), self.data, self.user_data, self.learning
        )

        self.list_: FrequencyList = self.data.get_frequency_list(
            listen_config.lists[0]
        )

    def play(
        self, question_id: str, audio_translations, learning_paths: list[Path]
    ) -> None:
        if self.player is None:
            logging.warning("MPV is not installed, cannot play audio.")
            return

        for translation in audio_translations:
            base_paths = self.base_audio_collection.get_paths(translation)
            self.player.play(str(base_paths[-1]))
            sleep(PAUSE_AFTER_PLAY)
        sleep(3)
        if len(learning_paths) == 1:
            learning_paths *= 2
        for path in learning_paths[:4]:
            self.player.play(str(path))
            sleep(PAUSE_AFTER_PLAY)
        sleep(2)
        self.listening.register(question_id, audio_translations)

    def listen__(self) -> None:
        index = 0
        for question_id in self.learning.get_safe_question_ids():
            print(f"{index}th word: {question_id}")
            index += 1
            if self.learning.has(question_id):
                if question_id not in self.safe_question_ids:
                    logging.info("Not safe time")
                    continue
                elif not self.teacher.check2(question_id):
                    continue

                self.process(question_id)

    def listen(self, start_from: int = 0, repeat: int = 1) -> None:
        logging.getLogger().setLevel(logging.ERROR)
        for index, question_id in enumerate(
            self.list_.get_words()[start_from:]
        ):
            if self.listening.get_hearings(question_id) >= repeat:
                continue

            if self.learning.has(question_id):
                if question_id not in self.safe_question_ids:
                    logging.info("Not safe time")
                    continue
                elif not self.teacher.check2(question_id):
                    continue

            self.process(question_id, index)

    def process(self, question_id: str, index: int):
        translations: list[str] = []
        if items := self.dictionary_collection.get_items(
            question_id, self.base_language
        ):
            for item in items:
                translations += item.get_one_word_definitions(
                    self.base_language
                )
        if not translations:
            logging.info("No one-word translations")
            return

        audio_translations: list[str] = []

        for translation in translations:
            if self.base_audio_collection.has(translation):
                audio_translations.append(translation)

        if audio_translations and self.learning_audio_collection.has(
            question_id
        ):
            learning_paths: list[Path] = (
                self.learning_audio_collection.get_paths(question_id)
            )
            print("   ", index, question_id, "—", ", ".join(translations))
            self.play(question_id, audio_translations[:3], learning_paths)
