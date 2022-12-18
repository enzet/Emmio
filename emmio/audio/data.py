from dataclasses import dataclass
from pathlib import Path

from emmio.audio.core import (
    AudioProvider,
    WikimediaCommonsAudioProvider,
    AudioCollection,
)


@dataclass
class AudioData:
    """Manager for the directory with dictionaries."""

    path: Path
    """The directory managed by this class."""

    def get_audio_provider(self, usage_config: dict) -> AudioProvider:

        match usage_config["id"]:
            case "wikimedia_commons":
                return WikimediaCommonsAudioProvider(self.path / "cache")
            case _:
                raise NotImplementedError()

    def get_audio_collection(
        self, usage_configs: list[dict]
    ) -> AudioCollection:
        return AudioCollection(
            [self.get_audio_provider(x) for x in usage_configs]
        )
