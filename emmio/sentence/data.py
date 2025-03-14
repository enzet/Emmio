from dataclasses import dataclass
from pathlib import Path

from emmio.core import ArtifactData
from emmio.language import construct_language
from emmio.sentence.config import SentencesConfig
from emmio.sentence.core import Sentences, SentencesCollection, SimpleSentences
from emmio.sentence.database import SentenceDatabase
from emmio.sentence.tatoeba import TatoebaSentences


@dataclass
class SentencesData(ArtifactData):
    """Manager for the directory with sentences."""

    path: Path
    """The directory managed by this class."""

    database: SentenceDatabase

    sentences: dict[str, Sentences]

    @classmethod
    def from_config(cls, path: Path) -> "SentencesData":
        """Initialize sentences from a directory."""
        config: dict = ArtifactData.read_config(path)

        database: SentenceDatabase = SentenceDatabase(path / "sentences.db")
        sentences: dict[str, Sentences] = {}
        for id_, data in config.items():
            sentences[id_] = SimpleSentences(path, SentencesConfig(**data))

        return cls(path, database, sentences)

    def get_sentences(self, usage_config: dict):
        match id_ := usage_config["id"]:
            case "tatoeba":
                language_1, language_2 = usage_config["languages"]
                return TatoebaSentences(
                    self.path,
                    construct_language(language_1),
                    construct_language(language_2),
                    self.database,
                )
            case _:
                return self.sentences[id_]

    def get_sentences_collection(
        self, usage_configs: list[dict]
    ) -> SentencesCollection:
        collection = []

        for usage_config in usage_configs:
            collection.append(self.get_sentences(usage_config))

        return SentencesCollection(collection)
