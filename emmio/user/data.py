import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from emmio.core import Record, Session
from emmio.language import Language
from emmio.learn.core import Learning, Response
from emmio.learn.data import LearnData
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lexicon.data import LexiconData
from emmio.listen.core import Listening
from emmio.listen.data import ListenData

LEARN_DIRECTORY_NAME: str = "learn"
LEXICON_DIRECTORY_NAME: str = "lexicon"
LISTEN_DIRECTORY_NAME: str = "listen"


@dataclass
class UserData:
    """Manager for user-related data."""

    config: dict
    """User data configuration."""

    path: Path
    """Path to the directory with user data.

    By default, it should be `~/.emmio/users/<user id>`, e.g.
    `~/.emmio/users/chloe`.
    """

    user_id: str
    """Unique user id.

    User id should be an ASCII string and be the same as the name of the
    directory with user data.  E.g. `chloe`.
    """

    user_name: str
    """Displayed user name.

    Unlike user id, it may contain any Unicode symbols.  E.g. `Chloé`.
    """

    _learn_data: LearnData | None
    """Data about user's learning processes."""

    _lexicon_data: LexiconData | None
    """Data about user's lexicon checking processes."""

    listenings: ListenData
    """Data about user's listening processes."""

    @classmethod
    def from_config(cls, user_id: str, path: Path, config: dict) -> Self:
        return cls(
            config,
            path,
            user_id,
            config["name"],
            None,
            None,
            ListenData.from_config(
                path / LISTEN_DIRECTORY_NAME, config["listen"]
            ),
        )

    def get_learn_data(self) -> LearnData:
        """Lazy-loads learning data."""

        if not self._learn_data:
            logging.info("Loading `%s` learning data...", self.user_id)
            self._learn_data = LearnData.from_config(
                self.path / LEARN_DIRECTORY_NAME, self.config["learn"]
            )
        return self._learn_data

    def get_lexicon_data(self) -> LexiconData:
        """Lazy-loads lexicon data."""

        if not self._lexicon_data:
            logging.info("Loading `%s` lexicon data...", self.user_id)
            self._lexicon_data = LexiconData.from_config(
                self.path / LEXICON_DIRECTORY_NAME, self.config["lexicon"]
            )
        return self._lexicon_data

    def get_all_learnings(self) -> Iterator[Learning]:
        return self.get_learn_data().get_learnings()

    def get_active_learnings(self) -> Iterator[Learning]:
        return self.get_learn_data().get_active_learnings()

    def get_learning(self, id_: str) -> Learning:
        return self.get_learn_data().get_learning(id_)

    def get_lexicons(
        self, languages: list[Language] | None = None
    ) -> list[Lexicon]:
        return self.get_lexicon_data().get_lexicons(languages)

    def get_lexicon_by_id(self, lexicon_id: str) -> Lexicon:
        return self.get_lexicon_data().get_lexicon_by_id(lexicon_id)

    def get_lexicons_by_language(self, language: Language) -> list[Lexicon]:
        return self.get_lexicon_data().get_lexicons_by_language(language)

    def is_known(self, word: str, language: Language) -> bool:
        learning_responses, lexicon_responses = self.get_word_status(
            word, language
        )
        if learning_responses:
            return True
        for lexicon_response in lexicon_responses:
            if lexicon_response == LexiconResponse.KNOW:
                return True

        return False

    def is_known_or_not_a_word(self, word: str, language: Language) -> bool:
        if self.is_known(word, language):
            return True

        _, lexicon_responses = self.get_word_status(word, language)
        for lexicon_response in lexicon_responses:
            if lexicon_response in [
                LexiconResponse.DONT_BUT_PROPER_NOUN_TOO,
                LexiconResponse.NOT_A_WORD,
            ]:
                return True

        return False

    def get_word_status(
        self, word: str, language: Language
    ) -> tuple[list[Response], list[LexiconResponse]]:
        learning_responses: list[Response] = []
        for learning in self.get_learn_data().get_learnings_by_language(
            language
        ):
            if knowledge := learning.get_knowledge(word):
                learning_responses.append(knowledge.get_last_response())

        lexicon_responses: list[LexiconResponse] = []
        for lexicon in self.get_lexicons_by_language(language):
            if lexicon.has(word):
                lexicon_responses.append(lexicon.get(word))

        return learning_responses, lexicon_responses

    def get_listening(self, listening_id: str) -> Listening:
        return self.listenings.get_listening(listening_id)

    def get_records(self) -> list:
        """Get all user records from all processes."""
        records: list = []
        for learning in self.get_active_learnings():
            records += learning.get_records()
        for lexicon in self.get_lexicon_data().get_lexicons():
            records += lexicon.get_records()
        records = sorted(records, key=lambda x: x.time)
        return records

    def get_session(self) -> list[Session]:
        sessions: list[Session] = []
        for learning in self.get_active_learnings():
            sessions += learning.get_sessions()
        for lexicon in self.get_lexicon_data().get_lexicons():
            sessions += lexicon.get_sessions()
        sessions = sorted(sessions, key=lambda x: x.get_start())
        return sessions

    def get_sessions_and_records(self) -> list[tuple[Session, list[Record]]]:
        records: list[Record] = self.get_records()
        sessions: list[Session] = self.get_session()

        result: list[tuple[Session, list[Record]]] = []
        session_index: int = 0
        record_index: int = 0
        current: tuple[Session, list[Record]] = (sessions[0], [])

        while True:
            session = sessions[session_index]
            record = records[record_index]

            if record.time < session.get_start():
                record_index += 1
                if record_index == len(records):
                    break
                continue

            if (
                end := session.get_end()
            ) and session.get_start() <= record.time <= end:
                current[1].append(record)
                record_index += 1
                if record_index == len(records):
                    break
                continue

            if (end := session.get_end()) and record.time > end:
                session_index += 1
                result.append(current)
                if session_index == len(sessions):
                    break
                current = (sessions[session_index], [])

        return result

    @classmethod
    def create(cls, path: Path, user_id: str, user_name: str) -> Self:
        """Create new user."""

        for directory in [
            LEARN_DIRECTORY_NAME,
            LEXICON_DIRECTORY_NAME,
            LISTEN_DIRECTORY_NAME,
        ]:
            (path / directory).mkdir()

        config: dict = {
            "id": user_id,
            "name": user_name,
            "learn": {},
            "lexicon": {},
            "listen": {},
        }
        user_data = cls(
            config,
            path,
            user_id,
            user_name,
            None,
            None,
            ListenData(path / LISTEN_DIRECTORY_NAME),
        )
        with (path / "config.json").open("w+", encoding="utf-8") as output_file:
            json.dump(config, output_file, ensure_ascii=False, indent=4)
            user_data.config = config

        return user_data

    def write_config(self) -> None:
        """Write configuration to the JSON file."""
        with (self.path / "config.json").open(
            "w+", encoding="utf-8"
        ) as output_file:
            config: dict = {
                "id": self.user_id,
                "name": self.user_name,
                "learn": {},
                "lexicon": {},
                "listen": {},
            }
            for learn_id, learning in self.get_learn_data().learnings.items():
                config["learn"][learn_id] = learning.config.dict()
            for lexicon_id, lexicon in self.get_lexicon_data().lexicons.items():
                config["lexicon"][lexicon_id] = lexicon.config.dict()
            for listen_id, listening in self.listenings.listenings.items():
                config["listen"][listen_id] = listening.config.dict()

            json.dump(config, output_file, ensure_ascii=False, indent=4)

    def get_frequency_lexicons(
        self, languages: list[Language] | None = None
    ) -> dict[Language, list[Lexicon]]:
        if not languages:
            return self.get_lexicon_data().get_frequency_lexicons()
        return {
            language: self.get_lexicon_data().get_frequency_lexicons_by_language(
                language
            )
            for language in languages
        }
