from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal

from emmio.language import Language
from emmio.sentence.config import SentencesConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


def split_sentence(
    text: str, language: Language
) -> list[tuple[str, Literal["word", "symbol"]]]:
    """Split sentence by words and symbols.

    :return tuples of text parts and its types, e.g. for `Hello, world!` the
        result should be
          - ("Hello", word),
          - (",", symbol),
          - (" ", symbol),
          - ("world", word),
          - ("!", symbol),
    """
    words: list[tuple[str, Literal["word", "symbol"]]] = []
    current: str = ""

    for position, symbol in enumerate(text):
        if language.has_symbol(symbol.lower()):
            current += symbol
        else:
            if current:
                words.append((current, "word"))
            words.append((symbol, "symbol"))
            current = ""

    if current:
        words.append((current, "word"))

    return words


@dataclass
class Sentence:
    """Some part of a text written in a single language.

    Sometimes it may contain two or more sentences or not be complete.
    """

    id_: int
    text: str

    def get_words(self, language: Language) -> list[tuple[str, str]]:
        return split_sentence(self.text, language)

    def rate(self, language: Language, user_data: "UserData") -> float:
        words: list[tuple[str, str]] = self.get_words(language)
        rating: int = 0
        word_number: int = 0
        for word, type_ in words:
            if type_ == "word":
                word_number += 1
                if user_data.is_known(word, language):
                    rating += 1
        if word_number == 0:
            return 0.0
        return rating / word_number


@dataclass
class SentenceTranslations:
    """Some part of a text written in a single language and its translations.

    Some translations may be transitive.
    """

    sentence: Sentence
    translations: List[Sentence]

    def rate(self, language: Language, user_data: "UserData") -> float:
        return self.sentence.rate(language, user_data)


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
        self,
        word: str,
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceTranslations]:
        """
        Get list of sentences with translations that contain requested word.

        It is assumed that list order doesn't change from request to request,
        but the order is specified by implementation.

        :param word: word to be presented in the resulting sentences
        :param ids_to_skip: identifiers of sentences to not include
        :param max_length: maximum length of the sentence to include
        :param max_number: maximum size of the resulting list
        """
        raise NotImplementedError()

    def filter_by_word_and_rate(
        self,
        word: str,
        user_data: "UserData",
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceTranslations]]:
        raise NotImplementedError()

    def get_most_known(
        self, user_data: "UserData"
    ) -> list[SentenceTranslations]:
        """Get top most known sentences."""
        raise NotImplementedError()


@dataclass
class SimpleSentences(Sentences):
    path: Path
    config: SentencesConfig

    def filter_by_word(
        self,
        word: str,
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceTranslations]:
        return []

    def filter_by_word_and_rate(
        self,
        word: str,
        user_data: "UserData",
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceTranslations]]:
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

        for sentences in self.collection:
            result += sentences.filter_by_word(word, ids_to_skip, max_length)

        return result

    def filter_by_word_and_rate(
        self,
        word: str,
        user_data: "UserData",
        ids_to_skip: set[int],
        max_length: int,
    ) -> list[tuple[float, SentenceTranslations]]:
        result: list[tuple[float, SentenceTranslations]] = []

        for sentences in self.collection:
            result += sentences.filter_by_word_and_rate(
                word, user_data, ids_to_skip, max_length
            )
        result.sort(key=lambda x: -x[0])

        return result

    def __len__(self):
        return sum(len(x) for x in self.collection)
