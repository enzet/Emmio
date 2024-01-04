from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio.core import Record, Session
from emmio.language import Language
from emmio.learn.core import Learning, Response
from emmio.learn.data import LearnData
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lexicon.data import LexiconData


@dataclass
class UserData:
    """Manager for user-related data."""

    path: Path
    """Path to the directory with user data.
    
    By default, it should be ``~/.emmio/users/<user id>``, e.g.
    ``~/.emmio/users/chloe``.
    """

    user_id: str
    """Unique user id.
    
    User id should be an ASCII string and be the same as the name of the
    directory with user data.  E.g. ``chloe``.
    """

    user_name: str
    """Displayed user name.
    
    Unlike user id, it may contain any Unicode symbols.  E.g. ``Chloé``.
    """

    learnings: LearnData
    """Data about user's learning processes."""

    lexicons: LexiconData
    """Data about user's lexicon checking processes."""

    @classmethod
    def from_config(cls, user_id: str, path: Path, config: dict) -> "UserData":
        return cls(
            path,
            user_id,
            config["name"],
            LearnData.from_config(path / "learn", config["learn"]),
            LexiconData.from_config(path / "lexicon", config["lexicon"]),
        )

    def get_learnings(self) -> Iterator[Learning]:
        return self.learnings.get_learnings()

    def get_active_learnings(self) -> Iterator[Learning]:
        return self.learnings.get_active_learnings()

    def get_learning(self, id_: str) -> Learning:
        return self.learnings.get_learning(id_)

    def get_lexicons(
        self, languages: list[Language] | None = None
    ) -> list[Lexicon]:
        return self.lexicons.get_lexicons(languages)

    def get_lexicon(self, language: Language) -> Lexicon:
        return self.lexicons.get_lexicon(language)

    def is_known(self, word: str, language: Language) -> bool:
        learning_responses, lexicon_response = self.get_word_status(
            word, language
        )
        if learning_responses:
            return True
        return lexicon_response == LexiconResponse.KNOW

    def is_known_or_not_a_word(self, word: str, language: Language) -> bool:
        learning_responses, lexicon_response = self.get_word_status(
            word, language
        )
        if lexicon_response in [
            LexiconResponse.DONT_BUT_PROPER_NOUN_TOO,
            LexiconResponse.NOT_A_WORD,
        ]:
            return True
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

    def get_read_processes(self) -> dict[str, Read]:
        return self.read_processes.get_read_processes()

    def get_listening(self, listening_id: str) -> Listening:
        return self.listenings.get_listening(listening_id)

    def get_records(self) -> list:
        """Get all user records from all processes."""
        records: list = []
        for learning in self.get_active_learnings():
            records += learning.get_records()
        for lexicon in self.lexicons.get_lexicons():
            records += lexicon.get_records()
        records = sorted(records, key=lambda x: x.time)
        return records

    def get_session(self):
        sessions: list = []
        for learning in self.get_active_learnings():
            sessions += learning.get_sessions()
        for lexicon in self.lexicons.get_lexicons():
            sessions += lexicon.get_sessions()
        sessions = sorted(sessions, key=lambda x: x.start)
        return sessions

    def get_sessions_and_records(self) -> list[tuple[Session, list[Record]]]:
        records: list[Record] = self.get_records()
        sessions: list[Session] = self.get_session()

        result = []
        session_index = 0
        record_index = 0
        current = (sessions[0], [])

        while True:
            session = sessions[session_index]
            record = records[record_index]

            if record.get_time() < session.get_start():
                record_index += 1
                if record_index == len(records):
                    break
                continue

            if session.get_start() <= record.get_time() <= session.get_end():
                current[1].append(record)
                record_index += 1
                if record_index == len(records):
                    break
                continue

            if record.get_time() > session.get_end():
                session_index += 1
                result.append(current)
                if session_index == len(sessions):
                    break
                current = (sessions[session_index], [])

        return result
