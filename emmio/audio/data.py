from dataclasses import dataclass
from pathlib import Path

from emmio.audio.config import AudioConfig
from emmio.audio.core import (
    AudioCollection,
    AudioProvider,
    DirectoryAudioProvider,
    WikimediaCommonsAudioProvider,
)
from emmio.core import ArtifactData
from emmio.language import Language


@dataclass
class AudioData(ArtifactData):
    """Manager for the directory with audio files."""

    path: Path
    """The directory managed by this class."""

    audio_providers: dict[str, AudioProvider]
    """Providers of audio files."""

    @classmethod
    def from_config(cls, path: Path) -> "AudioData":
        config: dict = ArtifactData.read_config(path)

        audio_providers: dict[str, AudioProvider] = {}
        for id_, data in config.items():
            audio_providers[id_] = DirectoryAudioProvider.from_config(
                path, AudioConfig(**data)
            )
        return cls(path, audio_providers)

    def get_audio_provider(self, usage_config: dict) -> AudioProvider:
        match id_ := usage_config["id"]:
            case "wikimedia_commons":
                return WikimediaCommonsAudioProvider(
                    Language.from_code(usage_config["language"]),
                    self.path / "cache",
                )
            case _:
                return self.audio_providers[id_]

    def get_audio_collection(
        self, usage_configs: list[dict]
    ) -> AudioCollection:
        return AudioCollection(
            [self.get_audio_provider(x) for x in usage_configs]
        )
