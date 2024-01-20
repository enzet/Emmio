import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from emmio.core import Record, Session
from emmio.language import Language
from emmio.learn.core import Learning, Response
from emmio.learn.data import LearnData
from emmio.listen.core import Listening
from emmio.listen.data import ListenData
from emmio.lexicon.core import Lexicon, LexiconResponse
from emmio.lexicon.data import LexiconData
from emmio.read.core import Read
from emmio.read.data import ReadData

LEARN_DIRECTORY_NAME: str = "learn"
LEXICON_DIRECTORY_NAME: str = "lexicon"
READ_DIRECTORY_NAME: str = "read"
LISTEN_DIRECTORY_NAME: str = "listen"


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

    read_processes: ReadData
    """Data about user's reading processes."""

    listenings: ListenData
    """Data about user's listening processes."""

    @classmethod
    def from_config(cls, user_id: str, path: Path, config: dict) -> "UserData":
        return cls(
            path,
            user_id,
            config["name"],
            LearnData.from_config(path / LEARN_DIRECTORY_NAME, config["learn"]),
            LexiconData.from_config(
                path / LEXICON_DIRECTORY_NAME, config["lexicon"]
            ),
            ReadData.from_config(path / READ_DIRECTORY_NAME, config["read"]),
            ListenData.from_config(
                path / LISTEN_DIRECTORY_NAME, config["listen"]
            ),
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

    def get_lexicon_by_id(self, lexicon_id: str) -> Lexicon:
        return self.lexicons.get_lexicon_by_id(lexicon_id)

    def get_lexicons_by_language(self, language: Language) -> list[Lexicon]:
        return self.lexicons.get_lexicons_by_language(language)

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

        learning_responses, lexicon_responses = self.get_word_status(
            word, language
        )
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
        for learning in self.learnings.get_learnings_by_language(language):
            if knowledge := learning.get_knowledge(word):
                learning_responses.append(knowledge.get_last_response())

        lexicon_responses: list[LexiconResponse] = []
        for lexicon in self.get_lexicons_by_language(language):
            if lexicon.has(word):
                lexicon_responses.append(lexicon.get(word))

        return learning_responses, lexicon_responses

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

    @classmethod
    def create(cls, path: Path, user_id: str, user_name: str) -> "UserData":
        """Create new user."""
        (path / LEARN_DIRECTORY_NAME).mkdir()
        (path / LEXICON_DIRECTORY_NAME).mkdir()
        (path / READ_DIRECTORY_NAME).mkdir()
        (path / LISTEN_DIRECTORY_NAME).mkdir()

        result: "UserData" = cls(
            path,
            user_id,
            user_name,
            LearnData(path / LEARN_DIRECTORY_NAME),
            LexiconData(path / LEXICON_DIRECTORY_NAME),
            ReadData(path / READ_DIRECTORY_NAME),
            ListenData(path / LISTEN_DIRECTORY_NAME),
        )
        result.write_config()

        return result

    def write_config(self) -> None:
        """Write configuration to the JSON file."""
        with (self.path / "config.json").open("w+") as output_file:
            config: dict = {
                "id": self.user_id,
                "name": self.user_name,
                "learn": {},
                "lexicon": {},
                "read": {},
                "listen": {},
            }
            for learn_id, learning in self.learnings.learnings.items():
                config["learn"][learn_id] = learning.config.dict()
            for lexicon_id, lexicon in self.lexicons.lexicons.items():
                config["lexicon"][lexicon_id] = lexicon.config.dict()
            for read_id, reading in self.read_processes.read_processes.items():
                config["read"][read_id] = reading.config.dict()
            for listen_id, listening in self.listenings.listenings.items():
                config["listen"][listen_id] = listening.config.dict()

            json.dump(config, output_file, ensure_ascii=False, indent=4)

    def get_frequency_lexicons(
        self, languages: list[Language] | None = None
    ) -> dict[Language, list[Lexicon]]:
        if not languages:
            return self.lexicons.get_frequency_lexicons()
        return {
            language: self.lexicons.get_frequency_lexicons_by_language(language)
            for language in languages
        }
