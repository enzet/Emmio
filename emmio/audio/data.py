"""Data for audio files."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.audio.config import AudioConfig, AudioUsageConfig
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
    def from_config(cls, path: Path) -> Self:
        """Create an audio data from a configuration.

        :param path: path to the configuration file
        :return: audio data
        """
        config: dict[str, Any] = ArtifactData.read_config(path)

        audio_providers: dict[str, AudioProvider] = {}
        for id_, data in config.items():
            audio_providers[id_] = DirectoryAudioProvider.from_config(
                path, AudioConfig(**data)
            )
        return cls(path, audio_providers)

    def get_audio_provider(
        self, usage_config: AudioUsageConfig
    ) -> AudioProvider:
        """Get an audio provider from a usage configuration.

        :param usage_config: usage configuration
        :return: audio provider
        """
        match id_ := usage_config.id:
            case "wikimedia_commons":
                if usage_config.language is None:
                    raise ValueError(
                        "`language` is required for Wikimedia Commons audio."
                    )
                return WikimediaCommonsAudioProvider(
                    Language.from_code(usage_config.language),
                    self.path / "cache",
                )
            case _:
                if id_ in self.audio_providers:
                    return self.audio_providers[id_]
                raise ValueError(f"Unknown audio provider: `{id_}`.")

    def get_audio_collection(
        self, usage_configs: list[AudioUsageConfig]
    ) -> AudioCollection:
        """Get an audio collection from a list of usage configurations.

        :param usage_configs: list of usage configurations
        :return: audio collection
        """
        return AudioCollection(
            [self.get_audio_provider(x) for x in usage_configs]
        )
