"""Server-side sessions: working memory kept between API requests.

A session object is only the selection policy's (or scheduler's) working
memory — answers themselves are persisted per request as ground truth. Losing
a session (restart, eviction, expiry) therefore never loses data: the working
memory is rebuilt from the database in O(answered words), at worst costing one
slightly suboptimal draw. Requests carry a session identifier as a *hint*, not
a lock: an unknown identifier transparently reopens the session.

Staleness is detected with a record-count stamp: every write path (answer,
propagation, undo — including ones that bypass the session, e.g. a learning
answer in the same language) changes the count, so one cheap query per request
notices out-of-band changes and triggers a rebuild.

Registries are per process. With several server workers each holds its own
working memory; that only affects draw quality, never correctness, and the
freshness stamp keeps the copies converging.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from emmio import postgres
from emmio.learn.config import LearnConfig
from emmio.learn.core import Learning, LearningSession
from emmio.lexicon.core import WordSelector, WordStates, create_selector
from emmio.lists.frequency_list import FrequencyList

SESSION_TTL: timedelta = timedelta(hours=2)
"""Idle time after which a session is finalized on next access."""

MAX_SESSIONS: int = 64
"""Per-registry cap; least recently used entries are finalized beyond it."""


def _new_session_id() -> str:
    """Generate an opaque session identifier."""
    return uuid.uuid4().hex


@dataclass
class LexiconCheckSession:
    """One user's open checking session on one lexicon.

    Holds the strategy's selector plus the in-memory copies of the per-word
    states and the recently-answered set that drive skip decisions, all kept
    in sync write-through as answers arrive.
    """

    session_id: str
    user_id: str
    lexicon_id: str
    language: str
    selection: str
    frequency_list: FrequencyList
    selector: WordSelector
    states: WordStates
    recent: set[str]
    stamp: int
    start: datetime
    last_action: datetime
    actions: int = 0

    lock: Any = field(default_factory=threading.RLock)
    """Reentrant lock serializing use."""

    def note_answer(
        self, word: str, code: str, *, to_skip: bool | None, when: datetime
    ) -> None:
        """Fold a user answer (already persisted) into the working memory."""
        self.states[word] = (code, to_skip)
        self.selector.record(word, code)
        self.recent.add(word)
        self.stamp += 1
        self.actions += 1
        self.last_action = when

    def note_auto(self, word: str, code: str, *, to_skip: bool | None) -> None:
        """Fold an automatically recorded (propagated) answer.

        Auto answers count toward the freshness stamp but are neither user
        actions nor "recently answered" (only real answers re-affirm a word).
        """
        self.states[word] = (code, to_skip)
        self.selector.record(word, code)
        self.stamp += 1


class LexiconSessionRegistry:
    """Open lexicon checking sessions, one per (user, lexicon)."""

    def __init__(self) -> None:
        self._sessions: OrderedDict[tuple[str, str], LexiconCheckSession] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def _load(
        self,
        user_id: str,
        lexicon_id: str,
        language: str,
        selection: str,
        frequency_list: FrequencyList,
    ) -> tuple[WordSelector, WordStates, set[str], int]:
        """Build selection working memory from ground truth."""
        stamp: int = postgres.count_lexicon_records(user_id, language)
        states: WordStates = postgres.get_language_word_states(
            user_id, language
        )
        recent: set[str] = postgres.get_recently_answered(user_id, language)
        answered: set[str] | None = None
        if selection == "top":
            answered = postgres.get_answered_words(user_id, lexicon_id)
        # The language-wide states above only drive skip decisions; the
        # selector's statistics are seeded from this lexicon's own records, so
        # a fresh lexicon runs its own coverage pass and sibling answers enter
        # one draw at a time via propagation, keeping the sample design valid.
        selector: WordSelector = create_selector(
            frequency_list,
            selection,
            postgres.get_lexicon_selector_states(user_id, lexicon_id),
            answered,
        )
        return selector, states, recent, stamp

    def open(
        self,
        user_id: str,
        lexicon_id: str,
        language: str,
        selection: str,
        frequency_list: FrequencyList,
        session_id: str | None = None,
    ) -> LexiconCheckSession:
        """Open a session, finalizing the previous one on this lexicon.

        :param session_id: keep this identifier (reopening after a restart or
            eviction); a fresh one is generated when not given
        """
        selector, states, recent, stamp = self._load(
            user_id, lexicon_id, language, selection, frequency_list
        )
        now: datetime = datetime.now(UTC)
        session: LexiconCheckSession = LexiconCheckSession(
            session_id=session_id or _new_session_id(),
            user_id=user_id,
            lexicon_id=lexicon_id,
            language=language,
            selection=selection,
            frequency_list=frequency_list,
            selector=selector,
            states=states,
            recent=recent,
            stamp=stamp,
            start=now,
            last_action=now,
        )
        evicted: list[LexiconCheckSession] = []
        with self._lock:
            previous = self._sessions.pop((user_id, lexicon_id), None)
            self._sessions[(user_id, lexicon_id)] = session
            while len(self._sessions) > MAX_SESSIONS:
                _key, old = self._sessions.popitem(last=False)
                evicted.append(old)
        if previous is not None:
            self._finalize(previous)
        for old in evicted:
            self._finalize(old)
        return session

    def acquire(
        self,
        user_id: str,
        lexicon_id: str,
        session_id: str,
        language: str,
        selection: str,
        frequency_list: FrequencyList,
    ) -> LexiconCheckSession:
        """Get the session for a request, reopening or refreshing as needed.

        The identifier is a hint: on a miss (restart, eviction, expiry, or an
        identifier from an older session) the session is rebuilt from ground
        truth under the requested identifier. On a hit, the freshness stamp is
        verified and the working memory reloaded if answers arrived through
        another path.
        """
        now: datetime = datetime.now(UTC)
        with self._lock:
            session = self._sessions.get((user_id, lexicon_id))
            if session is not None:
                if (
                    session.session_id != session_id
                    or now - session.last_action > SESSION_TTL
                ):
                    self._sessions.pop((user_id, lexicon_id))
                else:
                    self._sessions.move_to_end((user_id, lexicon_id))
                    self._refresh(session)
                    return session
        if session is not None:
            self._finalize(session)
        return self.open(
            user_id,
            lexicon_id,
            language,
            selection,
            frequency_list,
            session_id=session_id,
        )

    def _refresh(self, session: LexiconCheckSession) -> None:
        """Reload the working memory if answers arrived out of band."""
        with session.lock:
            stamp: int = postgres.count_lexicon_records(
                session.user_id, session.language
            )
            if stamp == session.stamp:
                return
            (
                session.selector,
                session.states,
                session.recent,
                session.stamp,
            ) = self._load(
                session.user_id,
                session.lexicon_id,
                session.language,
                session.selection,
                session.frequency_list,
            )

    def note_answer(
        self,
        user_id: str,
        lexicon_id: str,
        session_id: str,
        word: str,
        code: str,
        *,
        to_skip: bool | None,
        when: datetime,
    ) -> None:
        """Fold a persisted user answer into the open session, if it matches.

        A stale or unknown identifier is a no-op: the answer is already
        persisted, and any live session detects it through the freshness
        stamp on its next use.
        """
        with self._lock:
            session = self._sessions.get((user_id, lexicon_id))
        if session is None or session.session_id != session_id:
            return
        with session.lock:
            session.note_answer(word, code, to_skip=to_skip, when=when)

    def close(self, user_id: str, lexicon_id: str, session_id: str) -> None:
        """Close and finalize the session if it is the open one.

        Idempotent: closing an unknown or already-closed session is a no-op,
        so client retries are safe.
        """
        with self._lock:
            session = self._sessions.get((user_id, lexicon_id))
            if session is None or session.session_id != session_id:
                return
            self._sessions.pop((user_id, lexicon_id))
        self._finalize(session)

    def invalidate(self, user_id: str, lexicon_id: str) -> None:
        """Silently drop the session (settings changed, lexicon deleted).

        No session row is written: the session's premises (selection strategy,
        frequency list, or the lexicon itself) are gone.
        """
        with self._lock:
            self._sessions.pop((user_id, lexicon_id), None)

    def invalidate_user(self, user_id: str) -> None:
        """Silently drop every session of a deleted user."""
        with self._lock:
            for key in [key for key in self._sessions if key[0] == user_id]:
                self._sessions.pop(key)

    def reset(self) -> None:
        """Drop everything without finalizing (tests only)."""
        with self._lock:
            self._sessions.clear()

    def flush(self) -> None:
        """Finalize every open session (server shutdown)."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            self._finalize(session)

    @staticmethod
    def _finalize(session: LexiconCheckSession) -> None:
        """Write the session row; sessions without user actions leave none."""
        if session.actions == 0:
            return
        postgres.save_lexicon(
            session.user_id,
            session.lexicon_id,
            session.language,
            [],
            [(session.start, session.last_action)],
        )


@dataclass
class CourseSession:
    """An open explicit learning session on one course."""

    session_id: str
    type: str
    start: datetime
    last_action: datetime
    actions: int = 0


@dataclass
class LearningEntry:
    """A cached `Learning` instance with its freshness stamp."""

    learning: Learning
    stamp: int
    session: CourseSession | None = None
    lock: Any = field(default_factory=threading.RLock)
    """Reentrant lock serializing use (`threading.RLock`)."""


class LearningRegistry:
    """Cached `Learning` instances, one per (user, course).

    `Learning.from_config` replays every record of the course; caching the
    instance makes that a per-session cost instead of a per-request one. The
    optional explicit `CourseSession` groups answers into a `learn_sessions`
    row, like the CLI teacher does.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[tuple[str, str], LearningEntry] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def entry(
        self, user_id: str, course_id: str, config: dict
    ) -> LearningEntry:
        """Get the cached course, reloading it if stale or missing."""
        with self._lock:
            entry = self._entries.get((user_id, course_id))
            if entry is not None:
                self._entries.move_to_end((user_id, course_id))
        stamp: int = postgres.count_learn_records(user_id, course_id)
        if entry is not None:
            with entry.lock:
                if entry.stamp == stamp:
                    self._expire_session(entry)
                    return entry
                learning = self._load(user_id, course_id, config)
                entry.learning = learning
                entry.stamp = len(learning.process.records)
                self._expire_session(entry)
                return entry
        learning = self._load(user_id, course_id, config)
        entry = LearningEntry(
            learning=learning, stamp=len(learning.process.records)
        )
        evicted: list[LearningEntry] = []
        with self._lock:
            self._entries[(user_id, course_id)] = entry
            while len(self._entries) > MAX_SESSIONS:
                _key, old = self._entries.popitem(last=False)
                evicted.append(old)
        for old in evicted:
            with old.lock:
                self._close_session(old)
        return entry

    @staticmethod
    def _load(user_id: str, course_id: str, config: dict) -> Learning:
        """Load the course from the database (path is vestigial)."""
        return Learning.from_config(
            Path(), LearnConfig(**config), course_id, user_id
        )

    def open_session(
        self, user_id: str, course_id: str, config: dict, type_: str
    ) -> CourseSession:
        """Open an explicit session, closing a previous open one."""
        entry: LearningEntry = self.entry(user_id, course_id, config)
        now: datetime = datetime.now(UTC)
        with entry.lock:
            self._close_session(entry)
            entry.session = CourseSession(
                session_id=_new_session_id(),
                type=type_,
                start=now,
                last_action=now,
            )
            return entry.session

    def close_session(
        self, user_id: str, course_id: str, session_id: str
    ) -> None:
        """Close the explicit session if it is the open one; idempotent."""
        with self._lock:
            entry = self._entries.get((user_id, course_id))
        if entry is None:
            return
        with entry.lock:
            if (
                entry.session is not None
                and entry.session.session_id == session_id
            ):
                self._close_session(entry)

    def invalidate(self, user_id: str, course_id: str) -> None:
        """Drop the cached course (undo bypassed it, settings changed)."""
        with self._lock:
            self._entries.pop((user_id, course_id), None)

    def invalidate_user(self, user_id: str) -> None:
        """Silently drop every cached course of a deleted user."""
        with self._lock:
            for key in [key for key in self._entries if key[0] == user_id]:
                self._entries.pop(key)

    def reset(self) -> None:
        """Drop everything without writing session rows (tests only)."""
        with self._lock:
            self._entries.clear()

    def flush(self) -> None:
        """Close every open session (server shutdown)."""
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            with entry.lock:
                self._close_session(entry)

    def _expire_session(self, entry: LearningEntry) -> None:
        """Close the explicit session if it idled past the TTL."""
        if (
            entry.session is not None
            and datetime.now(UTC) - entry.session.last_action > SESSION_TTL
        ):
            self._close_session(entry)

    @staticmethod
    def _close_session(entry: LearningEntry) -> None:
        """Append the session row and persist it; empty sessions leave none."""
        session = entry.session
        entry.session = None
        if session is None or session.actions == 0:
            return
        entry.learning.process.sessions.append(
            LearningSession(
                type=session.type,
                start=session.start,
                end=session.last_action,
                actions=session.actions,
            )
        )
        entry.learning.write()


LEXICON_SESSIONS: LexiconSessionRegistry = LexiconSessionRegistry()
"""Process-wide registry of open lexicon checking sessions."""

LEARNING_REGISTRY: LearningRegistry = LearningRegistry()
"""Process-wide cache of loaded courses and their open sessions."""
