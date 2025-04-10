"""Core functionality for listening."""

import hashlib
import json
import logging
import os.path
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Self, override

try:
    import mpv
except (OSError, ImportError):
    logging.warning("MPV is not installed, audio playback will be disabled.")
    mpv = None

from emmio.audio.config import AudioConfig
from emmio.language import Language
from emmio.util import download

MIN_AUDIO_FILE_SIZE: int = 500
"""File smaller than this number of bytes should be treated as empty."""


class AudioProvider(ABC):
    """Provider that can play audio files with word pronunciations."""

    @abstractmethod
    def get_paths(self, word: str) -> list[Path]:
        """Get paths to audio files with the specified word.

        :param word: word or phrase to get audio for
        :return: list of paths or an empty list
        """
        raise NotImplementedError()

    @abstractmethod
    def play(self, word: str, repeat: int = 1) -> bool:
        """Play pronunciation of the word.

        :param word: word to play audio with pronunciation for
        :param repeat: number of times to play the audio
        :return: true iff an audio was played
        """
        raise NotImplementedError()

    @abstractmethod
    def has(self, word: str) -> bool:
        """Check whether the audio provider has audio for the word."""
        raise NotImplementedError()


@dataclass
class DirectoryAudioProvider(AudioProvider):
    """Audio provider that manages the directory with audio files."""

    directory: Path
    """Directory with audio files and subdirectories."""

    file_extension: str
    """Audio file extensions, e.g. `ogg`."""

    player = mpv.MPV() if mpv else None
    """Wrapper for the MPV player."""

    def __post_init__(self) -> None:
        """Initialize the audio provider."""

        self.path_pattern: re.Pattern[str] = re.compile(
            rf"(?P<word>[^()]*)\s*(\([^()]*\))?\s*\d?\.{self.file_extension}"
        )
        self.cache: dict[str, list[Path]] = defaultdict(list)
        self.fill_cache(self.directory)

    def fill_cache(self, path: Path) -> None:
        """Fill the cache with audio files.

        :param path: path to the directory with audio files or an audio file
        """
        if path.is_dir():
            for sub_path in path.iterdir():
                self.fill_cache(sub_path)
        elif path.is_file():
            if matcher := re.match(self.path_pattern, path.name):
                self.cache[matcher.group("word")].append(path)
            else:
                logging.warning("Unknown file `%s`.", path)

    @classmethod
    def from_config(cls, path: Path, config: AudioConfig) -> Self:
        """Create an audio provider from a configuration.

        :param path: path to the directory with audio files
        :param config: configuration of a collection of audio files
        """
        return cls(path / config.directory_name, config.format)

    @override
    def get_paths(self, word: str) -> list[Path]:
        """Return paths of the audio files.

        Return an empty list if files do not exist.

        :param word: word to get audio for
        :return: list of paths to the audio files
        """
        return self.cache.get(word, [])

    @override
    def play(self, word: str, repeat: int = 1) -> bool:
        """Play the audio files.

        :param word: word to play audio for
        :param repeat: number of times to play the audio
        :return: true iff an audio was played
        """
        if self.player is None:
            logging.warning("MPV is not installed, cannot play audio.")
            return False

        if paths := self.get_paths(word):
            for _ in range(repeat):
                logging.info("Playing `%s`...", paths[0])
                try:
                    self.player.play(str(paths[0]))
                # pylint: disable=broad-exception-caught
                # We want to catch and ignore all exceptions.
                except Exception as e:
                    logging.error("Unable to play `%s`.", paths[0])
                    logging.error(e)
            return True

        logging.debug("Audio was not found in `%s`.", self.directory)
        return False

    @override
    def has(self, word: str) -> bool:
        """Check whether the audio provider has audio for the word.

        :param word: word to check audio for
        :return: true iff an audio is available
        """
        return bool(self.get_paths(word))


class WikimediaCommonsAudioProvider(AudioProvider):
    """Audio provider for Wikimedia Commons.

    Downloads and plays audio files with word pronunciations from Wikimedia
    Commons.
    """

    def __init__(self, language: Language, cache_directory: Path) -> None:
        """Initialize the audio provider.

        :param language: language of the audio files
        :param cache_directory: path to the directory with cache files
        """
        self.cache_directory: Path = cache_directory / "wikimedia_commons"
        self.player = mpv.MPV() if mpv else None
        self.language: Language = language

        cache_file: Path = (
            cache_directory / f"wikimedia_commons_{language.get_code()}.json"
        )
        with cache_file.open(encoding="utf-8") as input_file:
            self.cache = json.load(input_file)

    @override
    def get_paths(self, word: str) -> list[Path]:

        if path := self.get_path(word):
            return [path]
        return []

    @staticmethod
    def download(name: str, cache_path: Path) -> bool:
        """Download the audio file.

        :param name: name of the audio file
        :param cache_path: path to the cache file
        :return: true iff the audio file was successfully downloaded
        """
        hashcode: str = hashlib.md5(name.encode()).hexdigest()[:2]
        url: str = (
            "https://upload.wikimedia.org/wikipedia/commons"
            f"/{hashcode[0]}/{hashcode}/{name}"
        )
        download(url, cache_path)
        if not cache_path.exists():
            return False
        return os.path.getsize(cache_path) > MIN_AUDIO_FILE_SIZE

    def get_path(self, word: str) -> Path | None:
        """Return path of the audio file or `None` if file does not exist.

        For Wikimedia Commons hashing scheme see
        https://commons.wikimedia.org/wiki/Commons:FAQ, part
        "What are the strangely named components in file paths?"

        :param word: word to get audio for
        :return: path to the audio file or `None` if file does not exist
        """
        if word not in self.cache:
            return None

        directory: Path = self.cache_directory / self.language.get_code()
        directory.mkdir(exist_ok=True, parents=True)

        name: str = self.cache[word].replace(" ", "_")
        cache_path: Path = directory / name

        if not cache_path.exists():
            downloaded = WikimediaCommonsAudioProvider.download(
                name, cache_path
            )
            if not downloaded:
                name = name[0].upper() + name[1:]
                cache_path = directory / name
                WikimediaCommonsAudioProvider.download(name, cache_path)

        if (
            cache_path.exists()
            and os.path.getsize(cache_path) > MIN_AUDIO_FILE_SIZE
        ):
            return cache_path

        return None

    @override
    def play(self, word: str, repeat: int = 1) -> bool:

        if self.player is None:
            logging.warning("MPV is not installed, cannot play audio.")
            return False

        if path := self.get_path(word):
            for _ in range(repeat):
                logging.info("Playing `%s`...", path)
                try:
                    self.player.play(str(path))
                # pylint: disable=broad-exception-caught
                # We want to catch and ignore all exceptions.
                except Exception as e:
                    logging.error("Unable to play `%s`.", path)
                    logging.error(e)
            return True

        return False

    @override
    def has(self, word: str) -> bool:
        """Check whether Wikimedia Commons file is available.

        Check whether Wikimedia Commons has audio file for the word and file is
        downloadable (if there is at least internet connection).
        """
        return self.get_path(word) is not None


@dataclass
class AudioCollection:
    """Collection of audio providers."""

    audio_providers: list[AudioProvider]
    """List of audio providers sorted by priority."""

    def get_paths(self, word: str) -> list[Path]:
        """Get paths to audio files with the specified word.

        :param word: word to get audio paths for
        :return: list of paths to the audio files
        """
        result: list[Path] = []
        for audio_provider in self.audio_providers:
            result += audio_provider.get_paths(word)
        return result

    def play(self, word: str, repeat: int = 1) -> bool:
        """Play pronunciations of the word from different providers.

        :param word: word to play pronunciations for
        :param repeat: number of times to play each pronunciation
        :return: true iff at least one pronunciation was played
        """
        for audio in self.audio_providers:
            if audio.play(word, repeat):
                return True
        return False

    def has(self, word: str) -> bool:
        """Check whether the audio collection has audio for the word.

        :param word: word to check audio for
        :return: true iff at least one pronunciation is available
        """
        for audio_provider in self.audio_providers:
            if audio_provider.has(word):
                return True
        return False
