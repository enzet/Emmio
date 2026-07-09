"""Sentences data."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from emmio.catalog import TATOEBA_LANGUAGES
from emmio.core import ArtifactData
from emmio.language import KnownLanguages, Language
from emmio.sentence.config import (
    SentenceConfig,
    SentencesUsageConfig,
    SentenceType,
)
from emmio.sentence.core import (
    SentenceAndTranslations,
    Sentences,
    SimpleOneLanguageSentences,
    SimpleTwoLanguagesSentences,
)
from emmio.sentence.database import TatoebaDatabase
from emmio.sentence.tatoeba import TatoebaSentences


@dataclass
class SentencesData(ArtifactData):
    """Manager for the directory with sentences."""

    path: Path
    """The directory managed by this class."""

    database: TatoebaDatabase
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
        sentences: dict[str, Sentences] = {}

        for id_, data in configs.items():
            config: SentenceConfig = SentenceConfig(**data)

            if config.type == SentenceType.SIMPLE_ONE_LANGUAGE:
                sentences[id_] = SimpleOneLanguageSentences.from_config(
                    path, id_, SentenceConfig(**data)
                )
            elif config.type == SentenceType.SIMPLE_TWO_LANGUAGES:
                sentences[id_] = SimpleTwoLanguagesSentences.from_config(
                    path, id_, SentenceConfig(**data)
                )
            else:
                message = f"Unknown sentence type: `{config.type}`."
                raise ValueError(message)

        database_path: Path = path / "sentences.db"
        cache_path: Path = path / "cache"
        database: TatoebaDatabase = TatoebaDatabase(database_path, cache_path)

        return cls(path, database, sentences)

    def get_supported_languages(self) -> set[str]:
        """Get codes of languages with Tatoeba sentences, local or downloadable.

        Combines the downloaded `<part3>_sentences.tsv[.bz2]` cache files with
        the static `TATOEBA_LANGUAGES` catalog of languages whose export can be
        fetched on first use. Only languages Emmio knows a two-letter code for
        are returned.
        """
        code_by_part3: dict[str, str] = {
            language.get_part3(): language.get_code()
            for language in KnownLanguages.get_languages()
        }
        codes: set[str] = set(TATOEBA_LANGUAGES)
        for cache_file in (self.path / "cache").glob("*_sentences.tsv*"):
            part3: str = cache_file.name.split("_sentences", 1)[0]
            if (code := code_by_part3.get(part3)) is not None:
                codes.add(code)
        return codes

    def get(
        self,
        word: str,
        usage_configs: list[SentencesUsageConfig],
        max_number: int = 1000,
    ) -> list[SentenceAndTranslations]:
        """Get sentences by a word.

        :param word: word to search for
        :param usage_configs: list of configurations for sentences
        :param max_number: cap on sentences inspected per source; keep it small
            when only one example is needed, as each sentence costs a lookup
        :return: list of sentences with the word
        """
        sentences: list[SentenceAndTranslations] = []

        for usage_config in usage_configs:
            if usage_config.id == "tatoeba":
                if self.tatoeba_sentences is None:
                    self.tatoeba_sentences = TatoebaSentences(
                        self.path, self.database
                    )
                translation_languages = (
                    [
                        Language.from_code(language)
                        for language in usage_config.translation_languages
                    ]
                    if usage_config.translation_languages
                    else []
                )
                sentences.extend(
                    self.tatoeba_sentences.get(
                        word,
                        Language.from_code(usage_config.language),
                        translation_languages,
                        max_number=max_number,
                    )
                )
            elif usage_config.id in self.sentences:
                value: Sentences = self.sentences[usage_config.id]
                if isinstance(value, SimpleTwoLanguagesSentences):
                    sentences.extend(value.get(word))
            else:
                message = f"Unknown sentence identifier: `{usage_config.id}`."
                raise ValueError(message)

        return sentences
