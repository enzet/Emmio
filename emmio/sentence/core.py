"""Core functionality for sentences."""

from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Self

from emmio.language import Language
from emmio.sentence.config import SentenceConfig

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class SentenceElement(Enum):
    """Type of sentence element."""

    WORD = "word"
    """Word, e.g. "book"."""

    SYMBOL = "symbol"
    """Symbol, e.g. ","."""


def split_sentence(
    text: str, language: Language
) -> list[tuple[str, SentenceElement]]:
    """Split sentence by words and symbols.

    :param text: text to split
    :param language: language of the text
    :return: tuples of text parts and its types, e.g. for "Hello, world!" the
        result should be
          - ("Hello", word),
          - (",", symbol),
          - (" ", symbol),
          - ("world", word),
          - ("!", symbol),
    """
    # TODO(enzet): Move this functionality to the language class.

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
class SentenceAndTranslations:
    """Some part of a text written in a single language and its translations.

    Some translations may be transitive.
    """

    sentence: Sentence
    """Sentence."""

    language: Language
    """Language of the sentence."""

    translations: dict[Language, list[Sentence]]
    """Translations of the sentence to other languages."""

    def rate(self, is_known: Callable[[str, Language], bool]) -> float:
        """Rate the sentence based on the knowledge of the words.

        :param is_known: function to check if a word is known
        :return: rating
        """
        return self.sentence.rate(self.language, is_known)


class Sentences(ABC):
    """Sentences as an artifact."""

    excluded_sentences_file_path: Path
    """Mapping from words to number identifiers of sentences that cannot be used
    for word learning.

    E.g. if the learning word is "potter", all sentences containing "Potter" as
    a name (e.g. "Harry Potter"), should be excluded, because back translation
    is trivial.
    """


@dataclass
class SimpleOneLanguageSentences(Sentences):
    """Collection of sentences in one language."""

    id_: str
    """Unique sentence string identifier."""

    sentences: list[Sentence]
    """List of sentences."""

    language: Language
    """Language."""

    @classmethod
    def from_config(cls, path: Path, id_: str, config: SentenceConfig) -> Self:
        """Initialize sentences from a directory.

        :param path: path to the directory with sentences
        :param id_: unique sentences identifier
        :param config: configuration of the sentences
        """
        if len(config.languages) != 1:
            message = "`languages` should contain exactly one language."
            raise ValueError(message)

        with (path / config.file_name).open(encoding="utf-8") as input_file:
            sentences: list[Sentence] = [
                Sentence(index, line.strip())
                for index, line in enumerate(input_file)
            ]

        return cls(id_, sentences, Language.from_code(config.languages[0]))


@dataclass
class SimpleTwoLanguagesSentences(Sentences):
    """Collection of sentences in two languages with translation relations."""

    id_: str
    """Unique sentence string identifier."""

    sentences: list[SentenceAndTranslations]
    """List of sentences."""

    language_1: Language
    """First language."""

    language_2: Language
    """Second language."""

    NUMBER_OF_LANGUAGES: int = 2

    @classmethod
    def from_config(cls, path: Path, id_: str, config: SentenceConfig) -> Self:
        """Initialize sentences from a directory.

        :param path: path to the directory with sentences
        :param id_: unique sentences identifier
        :param config: configuration of the sentences
        """
        if (
            not config.languages
            or len(config.languages)
            != SimpleTwoLanguagesSentences.NUMBER_OF_LANGUAGES
        ):
            message = "`languages` should contain exactly two languages."
            raise ValueError(message)

        language_1: Language = Language.from_code(config.languages[0])
        language_2: Language = Language.from_code(config.languages[1])

        sentences: list[SentenceAndTranslations] = []

        with (path / config.file_name).open(encoding="utf-8") as input_file:
            index: int = 0
            while True:
                text: str = input_file.readline().strip()
                if not text:
                    break
                translation: str = input_file.readline().strip()
                if not translation:
                    message = f'Translation for "{text}" is missing.'
                    raise ValueError(message)

                sentences.append(
                    SentenceAndTranslations(
                        Sentence(index, text),
                        language_1,
                        {language_2: [Sentence(index + 1, translation)]},
                    )
                )
                index += 2

        return cls(id_, sentences, language_1, language_2)

    def get(
        self,
        word: str,
        ids_to_skip: set[int] | None = None,
        max_length: int | None = None,
        max_number: int | None = 1000,
    ) -> list[SentenceAndTranslations]:
        """Get sentences."""
        return [
            sentence
            for sentence in self.sentences
            if word in sentence.sentence.text
            and sentence.sentence.id_ not in ids_to_skip
            and len(sentence.sentence.text) <= max_length
        ][:max_number]

    def get_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
        max_number: int | None = 1000,
    ) -> list[tuple[float, SentenceAndTranslations]]:
        """Get sentences with ratings."""
        return self.rate(
            is_known,
            self.filter_by_word(word, ids_to_skip, max_length, max_number),
        )


@dataclass
class SentencesCollection:
    """Collection of sentences."""

    collection: list[Sentences]
    """List of sentences."""

    def get(
        self, word: str, ids_to_skip: set[int], max_length: int
    ) -> list[SentenceAndTranslations]:
        """Get list of sentences with translations that contain requested word.

        :param word: word to be presented in the resulting sentences
        :param ids_to_skip: identifiers of sentences to exclude
        :param max_length: maximum length of the sentence to include
        """
        result: list[SentenceAndTranslations] = []

        for sentences in self.collection:
            result += sentences.get(word, ids_to_skip, max_length)

        return result

    def get_and_rate(
        self,
        word: str,
        is_known: Callable[[str, Language], bool],
        ids_to_skip: set[int],
        max_length: int,
    ) -> list[tuple[float, SentenceAndTranslations]]:
        """Get list of sentences with requested word and their ratings.

        :param word: word to be presented in the resulting sentences
        :param is_known: function to check if a word is known
        :param ids_to_skip: identifiers of sentences to exclude
        :param max_length: maximum length of the sentence to include
        """
        result: list[tuple[float, SentenceAndTranslations]] = []

        for sentences in self.collection:
            result += sentences.get_rate(
                word, is_known, ids_to_skip, max_length
            )
        result.sort(key=lambda record: -record[0])

        return result
