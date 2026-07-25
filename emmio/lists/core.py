"""Frequency list utility."""

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import override

from emmio.language import Language


class List(ABC):
    """Interface for word lists and frequency lists."""

    @abstractmethod
    def get_name(self) -> str | None:
        """Get list name."""
        raise NotImplementedError

    @abstractmethod
    def get_words(self) -> list[str]:
        """Get ordered list of words."""
        raise NotImplementedError


@dataclass
class SymbolList(List):
    """A language's alphabet, treated as a list of single-character "words".

    Backs a `LearningType.SYMBOL` learning: unlike other lists, it is not
    loaded from a file or configuration, but synthesized from
    `Language.symbols`.
    """

    language: Language
    """The language whose alphabet this is."""

    @override
    def get_name(self) -> str:
        return f"{self.language.get_name()} alphabet"

    @override
    def get_words(self) -> list[str]:
        return list(self.language.symbols)
