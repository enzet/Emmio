from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio.language import Language
from emmio.learn.core import Learning, Response
from emmio.learn.data import LearnData
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lexicon.data import LexiconData


@dataclass
class UserData:
    path: Path
    user_name: str
    learnings: LearnData
    lexicons: LexiconData

    @classmethod
    def from_config(cls, path: Path, config: dict) -> "UserData":
        return cls(
            path,
            config["name"],
            LearnData.from_config(path / "learn", config["learn"]),
            LexiconData.from_config(path / "lexicon", config["lexicon"]),
        )

    def get_active_learnings(self) -> Iterator[Learning]:
        return self.learnings.get_active_learnings()

    def get_learning(self, id_: str) -> Learning:
        return self.learnings.get_learning(id_)

    def get_lexicons(self) -> Iterator[Lexicon]:
        return self.lexicons.get_lexicons()

    def get_lexicon(self, language: Language) -> Lexicon:
        return self.lexicons.get_lexicon(language)

    def is_known(self, word: str, language: Language) -> bool:
        learning_responses, lexicon_response = self.get_word_status(
            word, language
        )
        if learning_responses:
            return True
        return lexicon_response == LexiconResponse.KNOW

    def get_word_status(
        self, word: str, language: Language
    ) -> tuple[list[Response], LexiconResponse]:
        learning_responses: list[Response] = []
        for learning in self.learnings.get_learnings_by_language(language):
            if knowledge := learning.get_knowledge(word):
                learning_responses.append(knowledge.get_last_response())
        lexicon = self.get_lexicon(language)
        lexicon_response = lexicon.get(word) if lexicon.has(word) else None

        return learning_responses, lexicon_response
