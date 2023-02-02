import json
from dataclasses import dataclass
from pathlib import Path

from emmio.audio.config import AudioConfig
from emmio.audio.core import (
    AudioCollection,
    AudioProvider,
    DirectoryAudioProvider,
    WikimediaCommonsAudioProvider,
)


@dataclass
class AudioData:
    """Manager for the directory with audio files."""

    path: Path
    """The directory managed by this class."""

    audio_providers: dict[str, AudioProvider]

    @classmethod
    def from_config(cls, path: Path) -> "AudioData":
        with (path / "config.json").open() as config_file:
            config: dict = json.load(config_file)
        audio_providers: dict[str, AudioProvider] = {}
        for id_, data in config.items():
            audio_providers[id_] = DirectoryAudioProvider.from_config(
                path, AudioConfig(**data)
            )
        return cls(path, audio_providers)

    def get_audio_provider(self, usage_config: dict) -> AudioProvider:
        match id_ := usage_config["id"]:
            case "wikimedia_commons":
                return WikimediaCommonsAudioProvider(self.path / "cache")
            case _:
                return self.audio_providers[id_]

    def get_audio_collection(
        self, usage_configs: list[dict]
    ) -> AudioCollection:
        return AudioCollection(
            [self.get_audio_provider(x) for x in usage_configs]
        )
