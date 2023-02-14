"""Frequency list utility."""

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class List:
    def get_name(self) -> str:
        """Get list name."""
        raise NotImplementedError()

    def get_info(self) -> str:
        """Get information about the list."""
        raise NotImplementedError()

    def get_words(self) -> list[str]:
        """Get ordered list of words."""
        raise NotImplementedError()
