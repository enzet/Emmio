import re
from dataclasses import dataclass
from typing import Any

from emmio import ui
from emmio.sentence.core import Sentence

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

HINT_GROUP_PREFIX: str = "hint"


@dataclass
class GrammarRule:
    """
    Grammar rule.
    """

    # Unique string rule identifier.
    id_: str

    themes: list[str]
    word: str

    # Identifiers of sentences manually selected for this rule.
    sentence_ids: set[int]

    @classmethod
    def deserialize(cls, structure: dict[str, Any]) -> "GrammarRule":
        return cls(
            structure["id"],
            structure["themes"],
            structure["word"],
            set(structure["sentence_ids"]),
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "id": self.id_,
            "themes": self.themes,
            "word": self.word,
            "sentence_ids": sorted(self.sentence_ids),
        }

    def ask(
        self, interface: ui.Interface, sentence: Sentence, translation: Sentence
    ) -> bool:
        """Print learning question for the grammar rule."""

        interface.print(translation.text)

        matcher: re.Match = self.learning_language_pattern.match(sentence.text)

        hints: list[str] = [
            matcher.group(index)
            for name, index in self.learning_language_pattern.groupindex.items()
            if name.startswith(HINT_GROUP_PREFIX)
        ]

        if hints:
            interface.print("Hints: " + " ".join([f"({x})" for x in hints]))

        answer: str = interface.input("> ")

        if answer == sentence.text:
            return True

        return False


class NotInterchangeableSensesGrammarRule(GrammarRule):
    id_: str = "not_interchangeable_senses"


class WordFormsGrammarRule(GrammarRule):
    def __init__(self, id_: str, word: str, forms: list[str]):
        self.id_: str = id_
        self.word: str = word
        self.forms: list[str] = forms


@dataclass
class Locator:
    sentence_id: int
    from_index: int
    to_index: int

    @classmethod
    def deserialize(cls, structure: dict[str, int]):
        return cls(structure["sentence"], structure["from"], structure["to"])

    def serialize(self) -> dict[str, int]:
        return {
            "sentence": self.sentence_id,
            "from": self.from_index,
            "to": self.to_index,
        }


@dataclass
class FormToSentence:
    map_: dict[str, Locator]


@dataclass
class SentenceChecker:
    # Pattern for sentences in known (native) language.
    known_language_pattern: re.Pattern

    # Pattern for sentences in learning (foreign) language.
    learning_language_pattern: re.Pattern

    def check(self):
        pass
