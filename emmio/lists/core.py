"""Frequency list utility."""

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from abc import ABC, abstractmethod


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
