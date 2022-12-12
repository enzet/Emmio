"""Frequency list utility."""

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class List:
    def get_info(self) -> str:
        raise NotImplementedError()

    def get_words(self) -> list[str]:
        raise NotImplementedError()
