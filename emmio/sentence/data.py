"""Sentences data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.core import ArtifactData
from emmio.language import Language
from emmio.sentence.config import SentenceConfig, SentenceType, SentencesUsageConfig
from emmio.sentence.core import (
    Sentences,
    SentencesCollection,
    SentenceAndTranslations,
    SimpleOneLanguageSentences,
    SimpleTwoLanguagesSentences,
)
from emmio.sentence.database import SentenceDatabase
from emmio.sentence.tatoeba import TatoebaSentences


@dataclass
class SentencesData(ArtifactData):
    """Manager for the directory with sentences."""

    path: Path
    """The directory managed by this class."""

    database: SentenceDatabase
    """The database with sentences."""

    sentences: dict[str, Sentences]
    """Mapping from unique sentence string identifier to sentence."""

    tatoeba_sentences: TatoebaSentences | None = None
    """Tatoeba sentences."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize sentences from a configuration.

        :param path: path to the directory with sentence data, usually
            `.emmio/sentences`
        """
        configs: dict[str, Any] = ArtifactData.read_config(path)

        for id_, data in configs.items():
            config: SentenceConfig = SentenceConfig(**data)

            if config.type == SentenceType.SIMPLE_ONE_LANGUAGE:
                sentences[id_] = SimpleOneLanguageSentences.from_config(
                    path, id_, SentenceConfig(**data)
                )
            elif config.type == SentenceType.SIMPLE_TWO_LANGUAGES:
                sentences: dict[str, Sentences] = {}
                for id_, data in config.items():
                    sentences[id_] = SimpleTwoLanguagesSentences.from_config(
                        path, id_, SentenceConfig(**data)
                    )
            else:
                raise ValueError(f"Unknown sentence type: `{config.type}`.")

        database_path: Path = path / "sentences.db"
        database: SentenceDatabase = SentenceDatabase(database_path)

        return cls(path, database, sentences)

    def get_by_word(
        self, word: str, usage_configs: list[SentencesUsageConfig]
    ) -> list[SentenceAndTranslations]:
        """Get sentences by a word.

        :param word: word to search for
        :param usage_configs: list of configurations for sentences
        :return: list of sentences with the word
        """
        sentences: list[SentenceAndTranslations] = []

        for usage_config in usage_configs:
            if usage_config.id == "__tatoeba":
                if self.tatoeba_sentences is None:
                    self.tatoeba_sentences = TatoebaSentences(
                        self.path,
                        self.database,
                    )
                sentences.extend(
                    self.tatoeba_sentences.get_by_word(
                        word,
                        usage_config.language,
                        usage_config.translation_languages,
                    )
                )
            else:
                if usage_config.id not in self.sentences:
                    sentences.extend(
                        self.sentences[usage_config.id].get_by_word(
                            word,
                            usage_config.language,
                            usage_config.translation_languages,
                        )
                    )
                else:
                    raise ValueError(
                        f"Unknown sentence identifier: `{usage_config.id}`."
                    )

        return sentences
