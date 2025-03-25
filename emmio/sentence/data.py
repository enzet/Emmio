"""Sentences data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.core import ArtifactData
from emmio.language import Language
from emmio.sentence.config import SentenceConfig, SentencesUsageConfig
from emmio.sentence.core import Sentences, SentencesCollection, SimpleSentences
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

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize sentences from a directory.

        :param path: path to the directory with sentences
        """
        config: dict[str, Any] = ArtifactData.read_config(path)

        sentences: dict[str, Sentences] = {}
        for id_, data in config.items():
            sentences[id_] = SimpleSentences.from_config(
                path, id_, SentenceConfig(**data)
            )

        database_path: Path = path / "sentences.db"
        database: SentenceDatabase = SentenceDatabase(database_path)

        return cls(path, database, sentences)

    def get_sentences(self, usage_config: SentencesUsageConfig) -> Sentences:
        """Get sentences by its identifier.

        :param usage_config: configuration for sentences
        :return: sentences
        """
        match id_ := usage_config.id:
            case "tatoeba":
                if usage_config.languages is None:
                    raise ValueError(
                        "Languages are required for Tatoeba sentences."
                    )
                language_1, language_2 = usage_config.languages
                return TatoebaSentences(
                    self.path,
                    Language.from_code(language_1),
                    Language.from_code(language_2),
                    self.database,
                )
            case _:
                if id_ in self.sentences:
                    return self.sentences[id_]
                raise ValueError(f"Unknown sentence type: `{id_}`.")

    def get_sentences_collection(
        self, usage_configs: list[SentencesUsageConfig]
    ) -> SentencesCollection:
        """Get sentences collection.

        :param usage_configs: list of configurations for sentences
        :return: sentences collection
        """
        collection: list[Sentences] = []

        for usage_config in usage_configs:
            collection.append(self.get_sentences(usage_config))

        return SentencesCollection(collection)
