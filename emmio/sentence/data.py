"""Sentences data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio.core import ArtifactData
from emmio.language import Language
from emmio.sentence.core import Sentences, SentencesCollection
from emmio.sentence.database import SentenceDatabase
from emmio.sentence.tatoeba import TatoebaSentences


@dataclass
class SentencesData(ArtifactData):
    """Manager for the directory with sentences."""

    path: Path
    """The directory managed by this class."""

    database: SentenceDatabase
    """The database with sentences."""

    @classmethod
    def from_config(cls, path: Path) -> Self:
        """Initialize sentences from a directory.

        :param path: path to the directory with sentences
        """
        # This will create the directory if it doesn't exist, but we don't need
        # any configuration, because we support only Tatoeba for now.
        ArtifactData.read_config(path)

        database_path: Path = path / "sentences.db"
        database: SentenceDatabase = SentenceDatabase(database_path)

        return cls(path, database)

    def get_sentences(self, usage_config: dict) -> Sentences:
        """Get sentences by its identifier.

        :param usage_config: configuration for sentences
        :return: sentences
        """
        match id_ := usage_config["id"]:
            case "tatoeba":
                language_1, language_2 = usage_config["languages"]
                return TatoebaSentences(
                    self.path,
                    Language.from_code(language_1),
                    Language.from_code(language_2),
                    self.database,
                )
            case _:
                # For now, only Tatoeba is supported.
                raise ValueError(f"Unknown sentence type: `{id_}`.")

    def get_sentences_collection(
        self, usage_configs: list[dict]
    ) -> SentencesCollection:
        """Get sentences collection.

        :param usage_configs: list of configurations for sentences
        :return: sentences collection
        """
        collection: list[Sentences] = []

        for usage_config in usage_configs:
            collection.append(self.get_sentences(usage_config))

        return SentencesCollection(collection)
