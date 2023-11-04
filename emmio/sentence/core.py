from dataclasses import dataclass
from pathlib import Path
from typing import List

from emmio.sentence.config import SentencesConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from emmio.user.data import UserData


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
    """Some part of a text written in a single language and its translations.

    Some translations may be transitive.
    """

    sentence: Sentence
    translations: List[Sentence]


class Sentences:
    excluded_sentences_file_path: Path
    """Mapping from words to number identifiers of sentences that cannot be used
    for word learning. 
    
    E.g. if the learning word is "potter", all sentences containing "Potter" as
    a name (e.g. "Harry Potter"), should be excluded, because back translation
    is trivial.
    """

    def __len__(self) -> int:
        """Return the total number of sentences."""
        return 0

    def filter_by_word(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        """
        Get list of sentences with translations that contain requested word.

        It is assumed that list order doesn't change from request to request,
        but the order is specified by implementation.

        :param word: word to be presented in the resulting sentences
        :param ids_to_skip: identifiers of sentences to not include
        :param max_length: maximum length of the sentence to include
        """
        raise NotImplementedError()

    def get_most_known(self, user_data: UserData) -> list[SentenceTranslations]:
        """Get top most known sentences."""
        raise NotImplementedError()


@dataclass
class SimpleSentences(Sentences):
    path: Path
    config: SentencesConfig

    def filter_by_word(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        return []

    def __len__(self) -> int:
        return 0


@dataclass
class SentencesCollection:
    collection: list[Sentences]

    def filter_by_word(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        result: list[SentenceTranslations] = []

        for sentence in self.collection:
            result += sentence.filter_by_word(word, ids_to_skip, max_length)

        return result

    def __len__(self):
        return sum(len(x) for x in self.collection)
