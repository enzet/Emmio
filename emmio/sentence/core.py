from dataclasses import dataclass
from typing import List

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


@dataclass
class Sentence:
    """
    Some part of a text written in a single language.  Sometimes it may contain
    two or more sentences or not be complete in itself.
    """

    id_: int
    text: str


@dataclass
class Translation:
    """
    Some part of a text written in a single language and its translations to
    other languages.  Some translations may be transitive.
    """

    sentence: Sentence
    translations: List[Sentence]
