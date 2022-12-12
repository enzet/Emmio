from dataclasses import dataclass
from pathlib import Path

from emmio.language import Language
from emmio.learn.core import Learning
from emmio.learn.data import LearnData
from emmio.lexicon.core import Lexicon
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

    def get_learnings(self) -> list[Learning]:
        return [
            x for x in self.learnings.learnings.values() if x.config.is_active
        ]

    def get_lexicon(self, language: Language) -> Lexicon:
        return self.lexicons.get_lexicon(language)
