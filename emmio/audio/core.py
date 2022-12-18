import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import mpv
import urllib3

from emmio.language import Language
from emmio.util import download


class AudioProvider:
    def play(self, word: str, language: Language) -> None:
        """Voice the word."""
        raise NotImplementedError()


class WikimediaCommonsAudioProvider(AudioProvider):
    def __init__(self, cache_directory: Path):
        self.cache_directory: Path = cache_directory / "en_wiktionary"
        self.player: mpv.MPV = mpv.MPV()

    def play(self, word: str, language: Language) -> None:
        """Voice the word."""
        directory: Path = self.cache_directory / language.get_code()
        directory.mkdir(exist_ok=True, parents=True)
        path: Path = directory / (word + ".ogg")
        language_code: str = language.get_code()
        name: str = f"{language_code[0].upper()}{language_code[1]}-{word}.ogg"
        hashcode: str = hashlib.md5(name.encode()).hexdigest()[:2]
        url: str = (
            "https://upload.wikimedia.org/wikipedia/commons"
            f"/{hashcode[0]}/{hashcode}/{name}"
        )
        logging.info(f"Downloading {url}...")

        download(url, path)

        if path.exists():
            self.player.play(str(path))


@dataclass
class AudioCollection:
    """Collection of audio providers."""

    audios: list[AudioProvider]

    def play(self, word: str, language: Language) -> None:
        """Voice the word."""
        for audio in self.audios:
            audio.play(word, language)
