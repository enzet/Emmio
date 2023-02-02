from dataclasses import dataclass
from pathlib import Path
from typing import List

from emmio.sentence.config import SentencesConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class Sentence:
    """
    Some part of a text written in a single language.

    Sometimes it may contain two or more sentences or not be complete.
    """

    id_: int
    text: str


@dataclass
class SentenceTranslations:
    """
    Some part of a text written in a single language and its translations.

    Some translations may be transitive.
    """

    sentence: Sentence
    translations: List[Sentence]


class Sentences:
    def filter_(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        raise NotImplementedError()

    def __len__(self) -> int:
        return 0


@dataclass
class SimpleSentences(Sentences):
    path: Path
    config: SentencesConfig

    def filter_(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        return []

    def __len__(self) -> int:
        return 0


@dataclass
class SentencesCollection:
    collection: list[Sentences]

    def filter_(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        result: list[SentenceTranslations] = []

        for s in self.collection:
            result += s.filter_(word, ids_to_skip, max_length)

        return result

    def __len__(self):
        return sum(len(x) for x in self.collection)
