import hashlib
import logging
import os.path
from dataclasses import dataclass
from pathlib import Path

import mpv

from emmio.audio.config import AudioConfig
from emmio.language import Language, ENGLISH
from emmio.util import download


MIN_AUDIO_FILE_SIZE: int = 500
"""File smaller than this number of bytes should be treated as empty."""


class AudioProvider:
    def play(self, word: str, language: Language, repeat: int = 1) -> bool:
        """
        Voice the word.

        :return true iff an audio was played
        """
        raise NotImplementedError()

    def has(self, word: str, language: Language) -> bool:
        raise NotImplementedError()


@dataclass
class DirectoryAudioProvider(AudioProvider):

    directory: Path
    file_extension: str
    player: mpv.MPV = mpv.MPV()

    @classmethod
    def from_config(cls, path: Path, config: AudioConfig):
        return cls(path / config.directory_name, config.format)

    def get_path(self, word: str, path: Path) -> Path | None:
        if path.is_file():
            if path.name == f"{word}.{self.file_extension}":
                return path
        if path.is_dir():
            for sub_path in path.iterdir():
                if path := self.get_path(word, sub_path):
                    return path
        return None

    def play(self, word: str, language: Language, repeat: int = 1) -> bool:
        if path := self.get_path(word, self.directory):
            for _ in range(repeat):
                logging.info(f"Playing {path}...")
                self.player.play(str(path))
                self.player.wait_for_playback()
            return True

        logging.info(f"Audio was not found in {self.directory}.")
        return False

    def has(self, word: str, language: Language) -> bool:
        return self.get_path(word, self.directory) is not None


class WikimediaCommonsAudioProvider(AudioProvider):
    def __init__(self, cache_directory: Path):
        self.cache_directory: Path = cache_directory / "wikimedia_commons"
        self.player: mpv.MPV = mpv.MPV()

    def get_path(self, word: str, language: Language) -> Path | None:
        directory: Path = self.cache_directory / language.get_code()
        directory.mkdir(exist_ok=True, parents=True)
        path: Path = directory / (word + ".ogg")

        if not path.exists():
            language_code: str = language.get_code()
            name: str
            if language == ENGLISH:
                name = f"En-us-{word}.ogg"
            else:
                name = (
                    f"{language_code[0].upper()}{language_code[1]}-{word}.ogg"
                )
            hashcode: str = hashlib.md5(name.encode()).hexdigest()[:2]
            url: str = (
                "https://upload.wikimedia.org/wikipedia/commons"
                f"/{hashcode[0]}/{hashcode}/{name}"
            )
            download(url, path)

        if path.exists() and os.path.getsize(path) > MIN_AUDIO_FILE_SIZE:
            return path

        return None

    def play(self, word: str, language: Language, repeat: int = 1) -> bool:
        """
        Voice the word.

        :param word: word to play audio with pronunciation for
        :param language: language of pronunciation
        :param repeat: number of times to play the audio
        """
        if path := self.get_path(word, language):
            for _ in range(repeat):
                logging.info(f"Playing {path}...")
                self.player.play(str(path))
                self.player.wait_for_playback()
            return True

        return False

    def has(self, word: str, language: Language) -> bool:
        return self.get_path(word, language) is not None


@dataclass
class AudioCollection:
    """Collection of audio providers."""

    audio_providers: list[AudioProvider]

    def play(self, word: str, language: Language, repeat: int = 1) -> bool:
        """Voice the word."""
        for audio in self.audio_providers:
            if audio.play(word, language, repeat):
                return True
        return False

    def has(self, word: str, language: Language):
        """Voice the word."""
        for audio in self.audio_providers:
            if audio.has(word, language):
                return True
        return False
