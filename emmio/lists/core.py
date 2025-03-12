"""Frequency list utility."""

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from abc import ABC, abstractmethod
from dataclasses import dataclass


class List(ABC):
    """Interface for word lists and frequency lists."""

    @abstractmethod
    def get_name(self) -> str:
        """Get list name."""
        raise NotImplementedError()

    @abstractmethod
    def get_info(self) -> str:
        """Get information about the list."""
        raise NotImplementedError()

    @abstractmethod
    def get_words(self) -> list[str]:
        """Get ordered list of words."""
        raise NotImplementedError()


@dataclass
class ListCollection:
    """Collection of lists."""

    collection: list[List]
    """Lists in the collection."""
