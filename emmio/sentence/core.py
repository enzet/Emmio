"""Core functionality for sentences."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from emmio.language import Language

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class SentenceElement(Enum):
    """Type of a sentence element."""

    WORD = "word"
    """Word, e.g. "book"."""

    SYMBOL = "symbol"
    """Symbol, e.g. ","."""


def split_sentence(
    text: str, language: Language
) -> list[tuple[str, SentenceElement]]:
    """Split sentence by words and symbols.

    :return tuples of text parts and its types, e.g. for `Hello, world!` the
        result should be
          - ("Hello", word),
          - (",", symbol),
          - (" ", symbol),
          - ("world", word),
          - ("!", symbol),
    """
    words: list[tuple[str, SentenceElement]] = []
    current: str = ""

    for symbol in text:
        if language.has_symbol(symbol.lower()):
            current += symbol
        else:
            if current:
                words.append((current, SentenceElement.WORD))
            words.append((symbol, SentenceElement.SYMBOL))
            current = ""

    if current:
        words.append((current, SentenceElement.WORD))

    return words


@dataclass
class Sentence:
    """Some part of a text written in a single language.

    Sometimes it may contain two or more sentences or not be complete.
    """

    id_: int
    """Unique sentence integer identifier."""

    text: str
    """Text of the sentence."""

    def get_words(
        self, language: Language
    ) -> list[tuple[str, SentenceElement]]:
        """Split sentence by words and symbols.

        :param language: language of the sentence
        :return: list of words and symbols
        """
        return split_sentence(self.text, language)

    def rate(
        self, language: Language, is_known: Callable[[str, Language], bool]
    ) -> float:
        """Rate the sentence based on the knowledge of the words.

        The higher the rating, the more the sentence is known for the user. 1
        means that all words are known. 0 means that none of the words are
        known.

        :param language: language of the sentence
        :param is_known: function to check if a word is known
        :return: rating
        """
        words: list[tuple[str, SentenceElement]] = self.get_words(language)
        rating: int = 0
        word_number: int = 0

        for word, type_ in words:
            if type_ == SentenceElement.WORD:
                word_number += 1
                if is_known(word, language):
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
    """Sentence."""

    translations: list[Sentence]
    """Translations of the sentence."""

    def rate(
        self, language: Language, is_known: Callable[[str, Language], bool]
    ) -> float:
        """Rate the sentence based on the knowledge of the words.

        :param language: language of the sentence
        :param is_known: function to check if a word is known
        :return: rating
        """
        return self.sentence.rate(language, is_known)


class Sentences(ABC):
    """Sentences."""

    excluded_sentences_file_path: Path
    """Mapping from words to number identifiers of sentences that cannot be used
    for word learning.

    E.g. if the learning word is "potter", all sentences containing "Potter" as
    a name (e.g. "Harry Potter"), should be excluded, because back translation
    is trivial.
    """

    @abstractmethod
    def __len__(self) -> int:
        """Return the total number of sentences."""
        raise NotImplementedError()

    @abstractmethod
    def filter_by_word(
        self,
        word: str,
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[SentenceTranslations]:
        """Get list of sentences with translations that contain requested word.

        It is assumed that list order doesn't change from request to request,
        but the order is specified by implementation.

        :param word: word to be presented in the resulting sentences
        :param ids_to_skip: identifiers of sentences to not include
        :param max_length: maximum length of the sentence to include
        :param max_number: maximum size of the resulting list
        """
        raise NotImplementedError()

    @abstractmethod
    def filter_by_word_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceTranslations]]:
        """Get list of sentences with translations that contain requested word.

        :param word: word to be presented in the resulting sentences
        :param is_known: function to check if a word is known
        :param ids_to_skip: identifiers of sentences to not include
        :param max_length: maximum length of the sentence to include
        :param max_number: maximum size of the resulting list
        """
        raise NotImplementedError()

    @staticmethod
    def rate(
        is_known: Callable[[str, Language], bool],
        sentence_translations,
        language: Language,
    ) -> list[tuple[float, SentenceTranslations]]:
        """Rate sentences based on the knowledge of the words.

        :param is_known: function to check if a word is known
        :param sentence_translations: list of sentences with translations
        :param language: language of the sentences
        :return: list of tuples of rating and sentence translations
        """
        result: list[tuple[float, SentenceTranslations]] = []
        for sentence_translation in sentence_translations:
            result.append(
                (
                    sentence_translation.rate(language, is_known),
                    sentence_translation,
                )
            )
        result.sort(key=lambda x: -x[0])
        return result


@dataclass
class SentencesCollection:
    """Collection of sentences."""

    collection: list[Sentences]
    """List of sentences."""

    def filter_by_word(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceTranslations]:
        """Get list of sentences with translations that contain requested word.

        :param word: word to be presented in the resulting sentences
        :param ids_to_skip: identifiers of sentences to exclude
        :param max_length: maximum length of the sentence to include
        """
        result: list[SentenceTranslations] = []

        for sentences in self.collection:
            result += sentences.filter_by_word(word, ids_to_skip, max_length)

        return result

    def filter_by_word_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
    ) -> list[tuple[float, SentenceTranslations]]:
        """Get list of sentences with requested word and their ratings.

        :param word: word to be presented in the resulting sentences
        :param is_known: function to check if a word is known
        :param ids_to_skip: identifiers of sentences to exclude
        :param max_length: maximum length of the sentence to include
        """
        result: list[tuple[float, SentenceTranslations]] = []

        for sentences in self.collection:
            result += sentences.filter_by_word_and_rate(
                word, is_known, ids_to_skip, max_length
            )
        result.sort(key=lambda x: -x[0])

        return result

    def __len__(self) -> int:
        """Return the total number of sentences."""
        return sum(len(x) for x in self.collection)
