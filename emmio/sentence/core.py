from dataclasses import dataclass
from pathlib import Path
from typing import List

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.sentence.config import SentencesConfig


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


@dataclass
class Sentences:
    path: Path
    config: SentencesConfig

    def filter_(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> SentenceTranslations | None:
        return None


@dataclass
class SentencesCollection:
    collection: list[Sentences]

    def filter_(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        r = []
        for sentences in self.collection:
            st = sentences.filter_(word, ids_to_skip, max_length)
            if st:
                r.append(st)
        return r
