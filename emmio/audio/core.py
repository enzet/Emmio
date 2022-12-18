import hashlib
import logging
import os.path
from dataclasses import dataclass
from pathlib import Path

import mpv

from emmio.audio.config import AudioConfig
from emmio.language import Language
from emmio.util import download


class AudioProvider:
    def play(self, word: str, language: Language) -> bool:
        """
        Voice the word.

        :return true iff an audio was played
        """
        raise NotImplementedError()


@dataclass
class DirectoryAudioProvider(AudioProvider):

    directory: Path
    file_extension: str
    player: mpv.MPV = mpv.MPV()

    @classmethod
    def from_config(cls, path: Path, config: AudioConfig):
        return cls(path / config.directory_name, config.format)

    def play_path(self, word: str, path: Path) -> bool:
        if path.is_file():
            if path.name == f"{word}.{self.file_extension}":
                for _ in range(2):
                    logging.info(f"Playing {path}...")
                    self.player.play(str(path))
                    self.player.wait_for_playback()
                return True
        if path.is_dir():
            for sub_path in path.iterdir():
                if self.play_path(word, sub_path):
                    return True
        return False

    def play(self, word: str, language: Language) -> bool:
        if not (played := self.play_path(word, self.directory)):
            logging.info(f"Audio was not found in {self.directory}.")
        return played


class WikimediaCommonsAudioProvider(AudioProvider):
    def __init__(self, cache_directory: Path):
        self.cache_directory: Path = cache_directory / "wikimedia_commons"
        self.player: mpv.MPV = mpv.MPV()

    def play(self, word: str, language: Language) -> bool:
        """Voice the word."""
        directory: Path = self.cache_directory / language.get_code()
        directory.mkdir(exist_ok=True, parents=True)
        path: Path = directory / (word + ".ogg")

        if not path.exists():
            language_code: str = language.get_code()
            name: str = (
                f"{language_code[0].upper()}{language_code[1]}-{word}.ogg"
            )
            hashcode: str = hashlib.md5(name.encode()).hexdigest()[:2]
            url: str = (
                "https://upload.wikimedia.org/wikipedia/commons"
                f"/{hashcode[0]}/{hashcode}/{name}"
            )
            download(url, path)

        if path.exists() and os.path.getsize(path) > 500:
            for _ in range(2):
                logging.info(f"Playing {path}...")
                self.player.play(str(path))
                self.player.wait_for_playback()
            return True

        return False


@dataclass
class AudioCollection:
    """Collection of audio providers."""

    audios: list[AudioProvider]

    def play(self, word: str, language: Language) -> bool:
        """Voice the word."""
        for audio in self.audios:
            if audio.play(word, language):
                return True
        return False
