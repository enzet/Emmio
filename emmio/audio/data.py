"""Data for audio files."""

import logging
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
from emmio.util import log_duration

logger: logging.Logger = logging.getLogger(__name__)


@dataclass
class AudioData(ArtifactData):
    """Manager for the directory with audio files."""

    path: Path
    """The directory managed by this class."""

    provider_configs: dict[str, Any]
    """Raw per-provider configuration, loaded lazily on first request."""

    audio_providers: dict[str, AudioProvider]
    """Cache of audio providers already built."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Create an audio data from a configuration.

        Providers are built lazily (on first request), not here: constructing a
        `DirectoryAudioProvider` recursively scans its whole directory, and the
        audio tree is large while a session touches only a couple of providers.

        :param path: path to the configuration file
        :return: audio data
        """
        return cls(path, ArtifactData.read_config(path), {})

    def get_language_provider_ids(self, language: str) -> list[str]:
        """Get ids of configured directory audio providers for a language.

        :param language: language code, e.g. `es`
        :return: ids whose configuration declares that language
        """
        return [
            id_
            for id_, config in self.provider_configs.items()
            if isinstance(config, dict) and config.get("language") == language
        ]

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
                    msg = "`language` is required for Wikimedia Commons audio."
                    raise ValueError(msg)
                # Cache per language: constructing the provider reads a JSON
                # word cache from disk.
                cache_key: str = f"wikimedia_commons:{usage_config.language}"
                if cache_key not in self.audio_providers:
                    self.audio_providers[cache_key] = (
                        WikimediaCommonsAudioProvider(
                            Language.from_code(usage_config.language),
                            self.path / "cache",
                        )
                    )
                return self.audio_providers[cache_key]
            case _:
                if id_ in self.audio_providers:
                    return self.audio_providers[id_]
                config = self.provider_configs.get(id_)
                if config is None:
                    msg = f"Unknown audio provider: `{id_}`."
                    raise ValueError(msg)
                with log_duration(f"load audio provider `{id_}`", logger):
                    self.audio_providers[id_] = (
                        DirectoryAudioProvider.from_config(
                            self.path, AudioConfig(**config)
                        )
                    )
                return self.audio_providers[id_]

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
