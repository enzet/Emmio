"""PostgreSQL storage for user learning and lexicon data.

This module is model-agnostic: it accepts and returns plain values, and the
conversion to and from Emmio data structures happens in `emmio.learn.core`
and `emmio.lexicon.core`. See `scripts/schema.sql` for the table definitions
and the `extra` JSONB key dictionaries.

The connection string is taken from the `EMMIO_DATABASE_URL` or
`DATABASE_URL` environment variable (default: `postgresql:///emmio`).
"""

import os
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

DEFAULT_DSN: str = "postgresql:///emmio"

LearnRecordRow = tuple[str, str, datetime, datetime | None, dict | None]
"""Question id, response code, response time, request time, extra."""

LearnSessionRow = tuple[str, datetime, datetime | None, int | None]
"""Session type, start, end, number of actions."""

LexiconRecordRow = tuple[str, str, datetime, dict | None]
"""Word, response code, response time, extra."""

LexiconSessionRow = tuple[datetime, datetime | None]
"""Session start and end."""

SAMPLING_SELECTIONS: frozenset[str] = frozenset(
    {"frequency", "logistic", "stratified", "threshold"}
)
"""Sampling selection strategies.

Selection strategies whose frequency list is the immutable sampling distribution
(identity). Others treat frequency lists as a mutable pool.
"""


def split_lexicon_config(config: dict) -> tuple[str, dict | None, dict]:
    """Split a flat lexicon configuration into its storage tiers.

    :param config: flat lexicon config (the `LexiconConfig` fields)
    :return: (selection, identity frequency list, mutable config). The identity
        frequency list is the sampling distribution for sampling strategies, or
        `None`; for pool strategies the frequency list goes into the mutable
        config under `frequency_lists`.
    """
    selection: str = config.get("selection") or "unknown"
    is_sampling: bool = selection in SAMPLING_SELECTIONS
    frequency_list: dict | None = config.get("frequency_list")

    identity_list: dict | None = frequency_list if is_sampling else None
    mutable: dict = {}
    if config.get("name"):
        mutable["name"] = config["name"]
    if config.get("dictionaries"):
        mutable["dictionaries"] = config["dictionaries"]
    if config.get("sentences"):
        mutable["sentences"] = config["sentences"]
    if not is_sampling and frequency_list:
        mutable["frequency_lists"] = [frequency_list]

    return selection, identity_list, mutable


_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    """Get the process-wide connection pool, opening it on first use.

    A single `psycopg.Connection` cannot be shared across threads safely, and
    FastAPI runs synchronous endpoints in a threadpool, so concurrent requests
    would corrupt each other's cursor and transaction state on one connection.
    A pool hands each unit of work its own connection instead (see
    `db_connection`), and bounds how many are open at once.
    """

    global _pool  # noqa: PLW0603  # pylint: disable=global-statement

    if _pool is None:
        dsn: str = os.environ.get(
            "EMMIO_DATABASE_URL", os.environ.get("DATABASE_URL", DEFAULT_DSN)
        )
        _pool = ConnectionPool(
            conninfo=dsn,
            # Always read timestamps as UTC, regardless of the machine time
            # zone, so that loaded data and JSON exports are deterministic.
            kwargs={"options": "-c timezone=UTC"},
            min_size=int(os.environ.get("EMMIO_DB_POOL_MIN", "1")),
            max_size=int(os.environ.get("EMMIO_DB_POOL_MAX", "20")),
            name="emmio",
            open=True,
        )
    return _pool


@contextmanager
def db_connection() -> Generator[psycopg.Connection]:
    """Borrow a connection from the pool for one unit of work.

    The connection is checked out on entry and returned to the pool on exit;
    on a clean exit the open transaction is committed, and on an exception it
    is rolled back. This replaces the previous per-call `.commit()`: callers
    open a cursor inside the block and let the block boundary commit::

        with db_connection() as connection, connection.cursor() as cursor:
            cursor.execute(...)
    """

    with _get_pool().connection() as connection:
        yield connection


@contextmanager
def db_cursor() -> Generator[psycopg.Cursor]:
    """Borrow a connection and open a cursor for one unit of work.

    The shorthand every query function here uses: `db_connection` with its
    transaction semantics (commit on clean exit, rollback on exception), with
    the cursor already opened::

        with db_cursor() as cursor:
            cursor.execute(...)
    """

    with db_connection() as connection, connection.cursor() as cursor:
        yield cursor


def ensure_user(user_id: str, name: str) -> None:
    """Create the user if it does not exist yet.

    :param user_id: stable string login, e.g. `john`
    :param name: display name
    """
    with db_cursor() as cursor:
        cursor.execute(
            "INSERT INTO users (user_id, name) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, name),
        )


def user_exists(user_id: str) -> bool:
    """Check whether a user with the given login exists."""

    with db_cursor() as cursor:
        cursor.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
        return cursor.fetchone() is not None


def register_user(
    user_id: str, name: str, email: str, hashed_password: str
) -> None:
    """Create a user with login credentials.

    :param user_id: stable string login, e.g. `john`
    :param name: display name
    :param email: unique email address used to log in
    :param hashed_password: already-hashed password (never the plaintext)
    :raises ValueError: if the login or email is already taken
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM users WHERE user_id = %s OR email = %s",
            (user_id, email),
        )
        if cursor.fetchone() is not None:
            message: str = (
                f"User `{user_id}` or email `{email}` already exists."
            )
            raise ValueError(message)
        cursor.execute(
            "INSERT INTO users (user_id, name, email, hashed_password) "
            "VALUES (%s, %s, %s, %s)",
            (user_id, name, email, hashed_password),
        )


def set_credentials(user_id: str, email: str, hashed_password: str) -> None:
    """Set (or replace) an existing user's login credentials.

    Useful for giving a CLI-only user (no password) the ability to log in via
    the API.

    :param user_id: stable string login, e.g. `john`
    :param email: unique email address used to log in
    :param hashed_password: already-hashed password (never the plaintext)
    :raises ValueError: if the user does not exist, or the email belongs to
        another user
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM users WHERE email = %s AND user_id <> %s",
            (email, user_id),
        )
        if cursor.fetchone() is not None:
            message: str = f"Email `{email}` is used by another user."
            raise ValueError(message)
        cursor.execute(
            "UPDATE users SET email = %s, hashed_password = %s "
            "WHERE user_id = %s RETURNING id",
            (email, hashed_password, user_id),
        )
        if cursor.fetchone() is None:
            message = f"Unknown user `{user_id}`."
            raise ValueError(message)


def get_credentials_by_email(email: str) -> tuple[str, str] | None:
    """Get (user login, password hash) for an email, or `None` if not found.

    Only users registered with a password (via the API) are returned; CLI-only
    users have no password and cannot log in.

    :param email: email address to look up
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT user_id, hashed_password FROM users "
            "WHERE email = %s AND hashed_password IS NOT NULL",
            (email,),
        )
        if row := cursor.fetchone():
            return row[0], row[1]
        return None


def get_password_hash(user_id: str) -> str | None:
    """Get a user's stored password hash, or `None` if they have no password.

    A CLI-only user (registered without credentials) has no hash. Used to
    verify the current password before a password change.

    :param user_id: user login, e.g. `john`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT hashed_password FROM users WHERE user_id = %s", (user_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None


def set_password(user_id: str, hashed_password: str) -> None:
    """Replace an existing user's password hash, keeping their email.

    :param user_id: user login, e.g. `john`
    :param hashed_password: already-hashed new password (never the plaintext)
    :raises ValueError: if the user does not exist
    """
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET hashed_password = %s "
            "WHERE user_id = %s RETURNING id",
            (hashed_password, user_id),
        )
        if cursor.fetchone() is None:
            message: str = f"Unknown user `{user_id}`."
            raise ValueError(message)


def list_users() -> list[tuple[str, str]]:
    """Get all users as (login, display name) pairs, ordered by login."""

    with db_cursor() as cursor:
        cursor.execute("SELECT user_id, name FROM users ORDER BY user_id")
        return [(row[0], row[1]) for row in cursor.fetchall()]


def get_user(user_id: str) -> tuple[str, str, str | None] | None:
    """Get a user as a (login, display name, email) tuple, or `None`.

    :param user_id: user login, e.g. `john`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT user_id, name, email FROM users WHERE user_id = %s",
            (user_id,),
        )
        if row := cursor.fetchone():
            return (row[0], row[1], row[2])
        return None


def get_users() -> list[tuple[str, str, dict]]:
    """Get every user as a (login, display name, config) tuple.

    `config` holds the user-level configuration sections that have no
    dedicated tables (currently `listen`, plus historical sections such as
    `read`).
    """
    with db_cursor() as cursor:
        cursor.execute("SELECT user_id, name, config FROM users ORDER BY id")
        return [(row[0], row[1], row[2] or {}) for row in cursor.fetchall()]


def get_user_config(user_id: str) -> dict | None:
    """Get a user's extra configuration sections, or `None` if no such user.

    :param user_id: user login, e.g. `john`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT config FROM users WHERE user_id = %s", (user_id,)
        )
        if row := cursor.fetchone():
            return row[0] or {}
        return None


def store_user_config(user_id: str, config: dict) -> None:
    """Replace a user's extra configuration sections.

    :param user_id: user login, e.g. `john`
    :param config: configuration sections without dedicated tables
        (e.g. `listen`)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET config = %s WHERE user_id = %s",
            (Jsonb(config), user_id),
        )


def get_account(user_id: str) -> dict[str, object] | None:
    """Get a user's account profile for a data export, or `None`.

    Returns the personal data held in the `users` row, excluding the password
    hash (a one-way secret of no use to the user). Intended for the
    "download my data" export (GDPR Art. 15 / 20).

    :param user_id: user login, e.g. `john`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT user_id, name, email, created_at "
            "FROM users WHERE user_id = %s",
            (user_id,),
        )
        if row := cursor.fetchone():
            return {
                "user_id": row[0],
                "name": row[1],
                "email": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
            }
        return None


def delete_user(user_id: str) -> bool:
    """Delete a user and all data they own.

    Removes the user's lexicons and courses with their words, records, and
    sessions. The schema has no `ON DELETE CASCADE`, so child rows are deleted
    in dependency order inside one transaction; either all of it goes or none.

    :param user_id: owning user login, e.g. `john`
    :return: whether a user was deleted (`False` if none existed)
    """
    with db_cursor() as cursor:
        cursor.execute("SELECT id FROM users WHERE user_id = %s", (user_id,))
        if not (row := cursor.fetchone()):
            return False
        user_db_id: int = int(row[0])

        # Lexicon data, deepest first.
        cursor.execute(
            "DELETE FROM lexicon_records r USING lexicon_words w, lexicons l "
            "WHERE r.word_id = w.id AND w.lexicon_id = l.id "
            "AND l.user_id = %s",
            (user_db_id,),
        )
        cursor.execute(
            "DELETE FROM lexicon_sessions s USING lexicons l "
            "WHERE s.lexicon_id = l.id AND l.user_id = %s",
            (user_db_id,),
        )
        cursor.execute(
            "DELETE FROM lexicon_words w USING lexicons l "
            "WHERE w.lexicon_id = l.id AND l.user_id = %s",
            (user_db_id,),
        )
        cursor.execute("DELETE FROM lexicons WHERE user_id = %s", (user_db_id,))

        # Learning data, deepest first.
        cursor.execute(
            "DELETE FROM learning_records r USING learnings l "
            "WHERE r.learning_id = l.id AND l.user_id = %s",
            (user_db_id,),
        )
        cursor.execute(
            "DELETE FROM learning_sessions s USING learnings l "
            "WHERE s.learning_id = l.id AND l.user_id = %s",
            (user_db_id,),
        )
        cursor.execute(
            "DELETE FROM learnings WHERE user_id = %s", (user_db_id,)
        )
        cursor.execute("DELETE FROM courses WHERE user_id = %s", (user_db_id,))

        cursor.execute("DELETE FROM users WHERE id = %s", (user_db_id,))
    return True


def list_learnings(
    user_id: str, course_id: str | None = None
) -> list[tuple[str, str, str, int, int, str]]:
    """Get a user's learnings with short info.

    :param user_id: owning user login, e.g. `john`
    :param course_id: if given, only learnings belonging to this course
    :return: (learning id, name, learning language, distinct words studied,
        total answers, learning type) tuples, ordered by learning id. Type
        is `word` for rows stored before `learning_type` existed.
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.learning_id, l.name, l.learning_language, "
            "(SELECT count(DISTINCT r.question_id) FROM learning_records r "
            "WHERE r.learning_id = l.id), "
            "(SELECT count(*) FROM learning_records r "
            "WHERE r.learning_id = l.id), "
            "COALESCE(l.config->>'learning_type', 'word') "
            "FROM learnings l "
            "JOIN users u ON u.id = l.user_id "
            "JOIN courses c ON c.id = l.course_id "
            "WHERE u.user_id = %s AND (%s::text IS NULL OR c.course_id = %s) "
            "ORDER BY l.learning_id",
            (user_id, course_id, course_id),
        )
        return [
            (row[0], row[1], row[2], row[3], row[4], row[5])
            for row in cursor.fetchall()
        ]


def list_courses(user_id: str) -> list[tuple[str, str, str, int]]:
    """Get a user's courses (language-level sets) with short info.

    :param user_id: owning user login, e.g. `john`
    :return: (course id, name, language, number of learnings) tuples, ordered
        by course id
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT c.course_id, c.name, c.language, "
            "(SELECT count(*) FROM learnings l WHERE l.course_id = c.id) "
            "FROM courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s ORDER BY c.course_id",
            (user_id,),
        )
        return [(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()]


def get_course(user_id: str, course_id: str) -> tuple[str, str] | None:
    """Get a course's (name, language), or `None` if it does not exist.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `armenian`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT c.name, c.language "
            "FROM courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s AND c.course_id = %s",
            (user_id, course_id),
        )
        return (row[0], row[1]) if (row := cursor.fetchone()) else None


def create_course(
    user_id: str, course_id: str, name: str, language: str
) -> None:
    """Create a new, empty course (language-level set).

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `armenian`
    :param name: display name, e.g. `Armenian`
    :param language: language code, e.g. `hy`
    """
    with db_cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        cursor.execute(
            "INSERT INTO courses (user_id, course_id, name, language) "
            "VALUES (%s, %s, %s, %s)",
            (user_db_id, course_id, name, language),
        )


def update_course_name(user_id: str, course_id: str, name: str) -> bool:
    """Rename a course.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `armenian`
    :param name: new display name, e.g. `Armenian`
    :return: whether a course was renamed (`False` if none existed)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE courses c SET name = %s "
            "FROM users u WHERE u.id = c.user_id "
            "AND u.user_id = %s AND c.course_id = %s",
            (name, user_id, course_id),
        )
        return cursor.rowcount > 0


def delete_course(user_id: str, course_id: str) -> bool:
    """Delete an empty course.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `armenian`
    :return: whether a course was deleted (`False` if none existed)
    :raise ValueError: if the course still has learnings
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT c.id FROM courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s AND c.course_id = %s",
            (user_id, course_id),
        )
        if not (row := cursor.fetchone()):
            return False
        course_db_id: int = int(row[0])

        cursor.execute(
            "SELECT count(*) FROM learnings WHERE course_id = %s",
            (course_db_id,),
        )
        count_row = cursor.fetchone()
        if count_row and int(count_row[0]) > 0:
            message: str = (
                f"Course `{course_id}` still has {count_row[0]} learning(s); "
                "delete them first."
            )
            raise ValueError(message)

        cursor.execute("DELETE FROM courses WHERE id = %s", (course_db_id,))
    return True


def list_lexicons(
    user_id: str,
) -> list[tuple[str, str, str | None, int, bool, str | None, dict | None]]:
    """Get a user's lexicons with short info.

    :param user_id: owning user login, e.g. `john`
    :return: (lexicon id, language, selection strategy, number of words
        checked, whether it is the main lexicon for its language, display
        name, frequency list usage configuration) tuples, ordered by
        lexicon id
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.lexicon_id, l.language, l.selection, "
            "(SELECT count(*) FROM lexicon_words w "
            "WHERE w.lexicon_id = l.id), "
            "l.is_main, l.config->>'name', l.frequency_list "
            "FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s ORDER BY l.lexicon_id",
            (user_id,),
        )
        return [
            (row[0], row[1], row[2], row[3], row[4], row[5], row[6])
            for row in cursor.fetchall()
        ]


def rename_lexicon(user_id: str, lexicon_id: str, new_lexicon_id: str) -> bool:
    """Change a lexicon's string identifier.

    Words, records, and sessions reference the lexicon's surrogate key, so
    they follow the rename untouched.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: current lexicon identifier, e.g. `fr`
    :param new_lexicon_id: identifier to rename to, e.g. `fr_books`
    :return: whether the lexicon existed
    :raises ValueError: if the user already has a lexicon with the new
        identifier
    """
    with db_cursor() as cursor:
        try:
            cursor.execute(
                "UPDATE lexicons l SET lexicon_id = %s FROM users u "
                "WHERE l.user_id = u.id AND u.user_id = %s "
                "AND l.lexicon_id = %s",
                (new_lexicon_id, user_id, lexicon_id),
            )
        except psycopg.errors.UniqueViolation as error:
            message: str = f"Lexicon `{new_lexicon_id}` already exists."
            raise ValueError(message) from error
        return cursor.rowcount > 0


def is_main_lexicon(user_id: str, lexicon_id: str) -> bool:
    """Check whether a lexicon is the main one for its language."""
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.is_main FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        row = cursor.fetchone()
        return bool(row and row[0])


def get_main_lexicons(
    user_id: str,
) -> list[tuple[str, str, str | None, dict | None]]:
    """Get the user's main lexicons, one per language.

    :return: (language, lexicon id, selection strategy, frequency list usage
        configuration) tuples, ordered by language
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.language, l.lexicon_id, l.selection, l.frequency_list "
            "FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.is_main ORDER BY l.language",
            (user_id,),
        )
        return [(row[0], row[1], row[2], row[3]) for row in cursor.fetchall()]


def has_main_lexicon(user_id: str, language: str) -> bool:
    """Check whether the user already has a main lexicon for a language."""
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.language = %s AND l.is_main",
            (user_id, language),
        )
        return cursor.fetchone() is not None


def set_main_lexicon(user_id: str, lexicon_id: str) -> None:
    """Make a lexicon the main one for its language.

    Any other main lexicon for the same language is cleared first, so the
    per-language "at most one main" rule holds (also enforced by a partial
    unique index).

    :raises ValueError: if the lexicon does not exist
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.id, l.language "
            "FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        if not (row := cursor.fetchone()):
            message: str = f"Unknown lexicon `{lexicon_id}`."
            raise ValueError(message)
        db_id, language = row
        cursor.execute(
            "UPDATE lexicons SET is_main = false FROM users u "
            "WHERE lexicons.user_id = u.id AND u.user_id = %s "
            "AND lexicons.language = %s AND lexicons.is_main",
            (user_id, language),
        )
        cursor.execute(
            "UPDATE lexicons SET is_main = true WHERE id = %s", (db_id,)
        )


def clear_main_lexicon(user_id: str, lexicon_id: str) -> None:
    """Clear a lexicon's main flag (its language then has no main)."""
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE lexicons SET is_main = false FROM users u "
            "WHERE lexicons.user_id = u.id AND u.user_id = %s "
            "AND lexicons.lexicon_id = %s",
            (user_id, lexicon_id),
        )


def get_lexicon_answer_sequences(
    user_id: str,
) -> dict[str, list[tuple[datetime, int]]]:
    """Get each lexicon's chronological know / don't-know answers.

    One query for all of a user's lexicons, used to compute the vocabulary
    rate without loading full lexicon objects.

    :param user_id: owning user login, e.g. `john`
    :return: mapping from lexicon id to a time-ordered list of
        (response time, 1 for "know" / 0 for "don't know")
    """
    result: dict[str, list[tuple[datetime, int]]] = {}
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.lexicon_id, r.response_time, r.response "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND r.response IN ('K', 'D') "
            "ORDER BY l.lexicon_id, r.id",
            (user_id,),
        )
        for lexicon_id, response_time, response in cursor.fetchall():
            result.setdefault(lexicon_id, []).append(
                (response_time, 1 if response == "K" else 0)
            )
    return result


def get_lexicon_answer_sequence(user_id: str, lexicon_id: str) -> list[int]:
    """Get one lexicon's chronological know / don't-know answers.

    The single-lexicon variant of `get_lexicon_answer_sequences`, without the
    response times: just what a rate estimator needs after every answer.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: time-ordered list of 1 for "know" / 0 for "don't know"
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT r.response FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s "
            "AND r.response IN ('K', 'D') "
            "ORDER BY r.id",
            (user_id, lexicon_id),
        )
        return [1 if row[0] == "K" else 0 for row in cursor.fetchall()]


def get_lexicon_record_log(
    user_id: str, lexicon_id: str
) -> list[tuple[str, str]]:
    """Get one lexicon's chronological (word, response code) log.

    Unlike `get_lexicon_answer_sequence`, keeps every response (including
    "not a word" resolutions) and the word itself, so the checking process
    can be replayed step by step.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: time-ordered list of (word, response code) pairs
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT w.word, r.response FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s "
            "ORDER BY r.id",
            (user_id, lexicon_id),
        )
        return [(word, response) for word, response in cursor.fetchall()]


def get_lexicon_dated_record_log(
    user_id: str, lexicon_id: str
) -> list[tuple[datetime, str, str]]:
    """Get one lexicon's chronological (time, word, response code) log.

    The dated variant of `get_lexicon_record_log`: the windowed rate history
    places every answer in time, and needs resolutions too.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: time-ordered list of (response time, word, response code)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT r.response_time, w.word, r.response "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s "
            "ORDER BY r.id",
            (user_id, lexicon_id),
        )
        return [
            (response_time, word, response)
            for response_time, word, response in cursor.fetchall()
        ]


def get_last_lexicon_record_id(user_id: str) -> int | None:
    """Get the id of the user's newest lexicon record.

    A cheap change marker for caching derived data (e.g. the rate graph):
    ids grow as answers are recorded and the newest record is the one an
    undo removes, so the maximum changes whenever the history changes.

    :param user_id: owning user login, e.g. `john`
    :return: the maximum record id, or `None` if there are no records
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT MAX(r.id) FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None


def _assemble_lexicon_config(
    language: str,
    selection: str | None,
    frequency_list: dict | None,
    config: dict | None,
) -> dict:
    """Build a flat configuration dictionary from the tiered database columns.

    Reassembles the in-memory `LexiconConfig` shape from identity columns plus
    the mutable `config` JSONB. The frequency list is the identity column for
    sampling strategies, or the first pooled list for pool strategies, so the
    runtime config keeps a single `frequency_list` regardless of tier.
    """
    config = config or {}
    if frequency_list is None:
        pool: list = config.get("frequency_lists") or []
        frequency_list = pool[0] if pool else None
    return {
        "language": language,
        "selection": selection or "unknown",
        "name": config.get("name"),
        "frequency_list": frequency_list,
        "dictionaries": config.get("dictionaries"),
        "sentences": config.get("sentences"),
    }


def get_lexicon_config(user_id: str, lexicon_id: str) -> dict | None:
    """Get a lexicon's reassembled config dict, or `None` if it does not exist.

    The dict matches the `LexiconConfig` fields (language, selection,
    frequency_list, dictionaries, sentences).

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.language, l.selection, l.frequency_list, l.config "
            "FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        if row := cursor.fetchone():
            return _assemble_lexicon_config(row[0], row[1], row[2], row[3])
        return None


def get_lexicon_configs(user_id: str) -> dict[str, dict]:
    """Get reassembled configuration dictionaries for all of a user's lexicons.

    :param user_id: owning user login, e.g. `john`
    :return: mapping from lexicon identifier to its config dict
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.lexicon_id, l.language, l.selection, l.frequency_list, "
            "l.config FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s ORDER BY l.lexicon_id",
            (user_id,),
        )
        return {
            row[0]: _assemble_lexicon_config(row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        }


def store_lexicon_config(user_id: str, lexicon_id: str, config: dict) -> None:
    """Create or update a lexicon's tiered configuration.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :param config: flat lexicon config (the `LexiconConfig` fields)
    """
    selection, identity_list, mutable = split_lexicon_config(config)
    language: str = config["language"]
    with db_cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        cursor.execute(
            "INSERT INTO lexicons "
            "(user_id, lexicon_id, language, selection, frequency_list, config)"
            " VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, lexicon_id) DO UPDATE SET "
            "language = excluded.language, selection = excluded.selection, "
            "frequency_list = excluded.frequency_list, "
            "config = excluded.config",
            (
                user_db_id,
                lexicon_id,
                language,
                selection,
                Jsonb(identity_list) if identity_list else None,
                Jsonb(mutable),
            ),
        )


LEARNING_CONFIG_KEYS: tuple[str, ...] = (
    "learning_type",
    "base_languages",
    "is_active",
    "scheme",
    "sentences",
    "dictionaries",
    "audio",
    "play_audio",
    "check_lexicon",
    "ask_lexicon",
    "max_for_day",
)
"""Mutable `LearningConfig` fields stored in the `config` JSONB.

Identity fields (`name`, `learning_language`, `course_id`) are columns
instead.
"""


def learning_config_jsonb(config: dict) -> dict:
    """Extract the mutable part of a flat learning configuration for storage.

    :param config: flat learning configuration (the `LearningConfig` fields)
    :return: the subset stored in the `config` JSONB column
    """
    return {key: config[key] for key in LEARNING_CONFIG_KEYS if key in config}


def _assemble_learning_config(
    name: str, learning_language: str, course_id: str, config: dict | None
) -> dict:
    """Build a flat learning config from the database columns plus JSONB."""
    return {
        "name": name,
        "learning_language": learning_language,
        "course_id": course_id,
        **(config or {}),
    }


def get_learning_config(user_id: str, learning_id: str) -> dict | None:
    """Get a learning's reassembled configuration dictionary.

    Return `None` if it does not exist.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.name, l.learning_language, c.course_id, l.config "
            "FROM learnings l "
            "JOIN users u ON u.id = l.user_id "
            "JOIN courses c ON c.id = l.course_id "
            "WHERE u.user_id = %s AND l.learning_id = %s",
            (user_id, learning_id),
        )
        if row := cursor.fetchone():
            return _assemble_learning_config(row[0], row[1], row[2], row[3])
        return None


def get_learning_configs(user_id: str) -> dict[str, dict]:
    """Get reassembled configuration dictionaries for all of a user's learnings.

    :param user_id: owning user login, e.g. `john`
    :return: mapping from learning identifier to its config dict
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.learning_id, l.name, l.learning_language, "
            "c.course_id, l.config "
            "FROM learnings l "
            "JOIN users u ON u.id = l.user_id "
            "JOIN courses c ON c.id = l.course_id "
            "WHERE u.user_id = %s ORDER BY l.learning_id",
            (user_id,),
        )
        return {
            row[0]: _assemble_learning_config(row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        }


def store_learning_config(user_id: str, learning_id: str, config: dict) -> None:
    """Create or update a learning's configuration.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    :param config: flat learning config (the `LearningConfig` fields)
    """
    with db_cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        course_db_id: int = _get_course_db_id(
            cursor, user_db_id, config["course_id"]
        )
        cursor.execute(
            "INSERT INTO learnings "
            "(user_id, learning_id, name, learning_language, course_id, "
            "config) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, learning_id) DO UPDATE SET "
            "name = excluded.name, "
            "learning_language = excluded.learning_language, "
            "config = excluded.config",
            (
                user_db_id,
                learning_id,
                config["name"],
                config["learning_language"],
                course_db_id,
                Jsonb(learning_config_jsonb(config)),
            ),
        )


def delete_learning(user_id: str, learning_id: str) -> bool:
    """Delete a single learning and all its records and sessions.

    The schema has no `ON DELETE CASCADE`, so child rows are removed in
    dependency order inside one transaction; either all of it goes or none.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    :return: whether a learning was deleted (`False` if none existed)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.id FROM learnings l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s",
            (user_id, learning_id),
        )
        if not (row := cursor.fetchone()):
            return False
        learning_db_id: int = int(row[0])

        # Deepest first: records and sessions before the learning row.
        cursor.execute(
            "DELETE FROM learning_records WHERE learning_id = %s",
            (learning_db_id,),
        )
        cursor.execute(
            "DELETE FROM learning_sessions WHERE learning_id = %s",
            (learning_db_id,),
        )
        cursor.execute("DELETE FROM learnings WHERE id = %s", (learning_db_id,))
    return True


def delete_lexicon(user_id: str, lexicon_id: str) -> bool:
    """Delete a single lexicon and all its words, records, and sessions.

    The schema has no `ON DELETE CASCADE`, so child rows are removed in
    dependency order inside one transaction; either all of it goes or none.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: whether a lexicon was deleted (`False` if none existed)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT l.id FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        if not (row := cursor.fetchone()):
            return False
        lexicon_db_id: int = int(row[0])

        # Deepest first: records (via words) and sessions before the words and
        # the lexicon row itself.
        cursor.execute(
            "DELETE FROM lexicon_records r USING lexicon_words w "
            "WHERE r.word_id = w.id AND w.lexicon_id = %s",
            (lexicon_db_id,),
        )
        cursor.execute(
            "DELETE FROM lexicon_sessions WHERE lexicon_id = %s",
            (lexicon_db_id,),
        )
        cursor.execute(
            "DELETE FROM lexicon_words WHERE lexicon_id = %s", (lexicon_db_id,)
        )
        cursor.execute("DELETE FROM lexicons WHERE id = %s", (lexicon_db_id,))
    return True


def get_answered_words(user_id: str, lexicon_id: str) -> set[str]:
    """Get the set of words already recorded in a user's lexicon.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT w.word "
            "FROM lexicon_words w JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        return {row[0] for row in cursor.fetchall()}


def get_lexicon_word_states(
    user_id: str, lexicon_id: str
) -> dict[str, str | None]:
    """Get each word's current cached response in one lexicon.

    Reads the per-word state cache (`lexicon_words.response`), so no record
    history is scanned. Used by new-word selection to know whether a candidate
    is already known (or marked "don't know") in a course's `check_lexicons` /
    `ask_lexicon`.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: mapping from word to its current response code (the value may be
        `None` when the word is recorded without a cached response)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT w.word, w.response "
            "FROM lexicon_words w JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        return {row[0]: row[1] for row in cursor.fetchall()}


def get_last_lexicon_answers(
    user_id: str, lexicon_id: str, words: list[str]
) -> dict[str, tuple[str, datetime]]:
    """Get each given word's most recent *user* answer in a lexicon.

    Used to show "last answer" context when a word is presented again.
    Auto/propagated records are ignored, so the time reflects when the user
    actually answered.

    :return: mapping word -> (response code, response time); words the user
        never answered are absent
    """
    if not words:
        return {}
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT ON (w.word) w.word, r.response, r.response_time "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s AND w.word = ANY(%s) "
            "AND (r.extra IS NULL OR NOT (r.extra ? 'at')) "
            "ORDER BY w.word, r.response_time DESC, r.id DESC",
            (user_id, lexicon_id, words),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def get_last_learn_answers(
    user_id: str, learning_id: str, questions: list[str]
) -> dict[str, tuple[str, datetime]]:
    """Get each given question's most recent answer in a learning.

    :return: mapping question -> (response code, response time); unanswered
        questions are absent
    """
    if not questions:
        return {}
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT ON (r.question_id) "
            "r.question_id, r.response, r.response_time "
            "FROM learning_records r "
            "JOIN learnings l ON l.id = r.learning_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s "
            "AND r.question_id = ANY(%s) "
            "ORDER BY r.question_id, r.response_time DESC, r.id DESC",
            (user_id, learning_id, questions),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def get_language_word_states(
    user_id: str, language: str
) -> dict[str, tuple[str | None, bool | None]]:
    """Get every word's latest state across a user's same-language lexicons.

    Loaded once per selection so the draw-and-record loop can decide, in
    memory, whether a drawn word should be presented or auto-answered
    (propagated). The most recently seen lexicon wins per word.

    :param user_id: owning user login, e.g. `john`
    :param language: language code shared by the lexicons
    :return: mapping from word to its (response code, to_skip)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT ON (w.word) w.word, w.response, w.to_skip "
            "FROM lexicon_words w "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.language = %s "
            "ORDER BY w.word, w.last_seen DESC NULLS LAST",
            (user_id, language),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def get_lexicon_selector_states(
    user_id: str, lexicon_id: str
) -> dict[str, tuple[str | None, bool | None]]:
    """Get every word's state in one lexicon.

    :return: mapping from word to its (response code, `to_skip`)
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT w.word, w.response, w.to_skip "
            "FROM lexicon_words w "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def get_recently_answered(
    user_id: str, language: str, recent_days: int = 30
) -> set[str]:
    """Get words the user *answered* in a language within the last days.

    Only real user answers count (auto/propagated records are ignored), so a
    word keeps being re-affirmed by propagation until the user actually
    re-answers it after the window. Drives the "propagate time" decision.

    :param user_id: owning user login, e.g. `john`
    :param language: language code shared by the lexicons
    :param recent_days: length of the window in days
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT w.word "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.language = %s "
            "AND r.response_time >= now() - make_interval(days => %s) "
            "AND (r.extra IS NULL OR NOT (r.extra ? 'at'))",
            (user_id, language, recent_days),
        )
        return {row[0] for row in cursor.fetchall()}


def count_lexicon_records(user_id: str, language: str) -> int:
    """Count lexicon records across a user's same-language lexicons.

    A cheap freshness stamp for session working memory: every write path
    (answer, propagation, undo) changes the count, so a cached selector can
    detect out-of-band changes with one query. Scoped to the language, not
    the lexicon, mirroring `get_language_word_states`.

    :param user_id: owning user login, e.g. `john`
    :param language: language code shared by the lexicons
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT count(*) "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.language = %s",
            (user_id, language),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def count_learning_records(user_id: str, learning_id: str) -> int:
    """Count learning records of a user's learning.

    The freshness stamp for a cached `Learning` instance: every write path
    (answer, undo) changes the count.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT count(*) "
            "FROM learning_records r "
            "JOIN learnings l ON l.id = r.learning_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s",
            (user_id, learning_id),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def delete_last_lexicon_record(user_id: str, lexicon_id: str) -> str | None:
    """Delete the most recent answer in a lexicon and return its word.

    Undoes a single answer: the word's cached state is rebuilt from its
    remaining records (or the word is dropped if it has none left), so it
    becomes selectable again.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: the word whose answer was removed, or `None` if there is nothing
        to undo
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT r.id, w.id, w.word "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s "
            "ORDER BY r.response_time DESC, r.id DESC LIMIT 1",
            (user_id, lexicon_id),
        )
        if not (row := cursor.fetchone()):
            return None
        record_id, word_id, word = row
        cursor.execute(
            "DELETE FROM lexicon_records WHERE id = %s", (record_id,)
        )
        cursor.execute(
            "SELECT response, response_time, extra FROM lexicon_records "
            "WHERE word_id = %s ORDER BY response_time DESC, id DESC LIMIT 1",
            (word_id,),
        )
        if latest := cursor.fetchone():
            response, response_time, extra = latest
            cursor.execute(
                "UPDATE lexicon_words SET response = %s, last_seen = %s, "
                "to_skip = %s WHERE id = %s",
                (response, response_time, (extra or {}).get("sk"), word_id),
            )
        else:
            cursor.execute(
                "DELETE FROM lexicon_words WHERE id = %s", (word_id,)
            )
    return str(word)


def _get_user_db_id(cursor: psycopg.Cursor, user_id: str) -> int:
    """Get internal user identifier, raising if the user does not exist."""

    cursor.execute("SELECT id FROM users WHERE user_id = %s", (user_id,))
    if row := cursor.fetchone():
        return int(row[0])
    message: str = f"Unknown user `{user_id}`; create it first."
    raise ValueError(message)


def _get_course_db_id(
    cursor: psycopg.Cursor, user_db_id: int, course_id: str
) -> int:
    """Get internal course identifier, raising if the course does not exist.

    Unlike learnings, courses are never auto-created: they must be created
    explicitly (`create_course`) before a learning can be added to them.
    """

    cursor.execute(
        "SELECT id FROM courses WHERE user_id = %s AND course_id = %s",
        (user_db_id, course_id),
    )
    if row := cursor.fetchone():
        return int(row[0])
    message: str = f"Unknown course `{course_id}`; create it first."
    raise ValueError(message)


def _get_learning_db_id(
    cursor: psycopg.Cursor,
    user_db_id: int,
    learning_id: str,
    name: str,
    language: str,
    course_db_id: int,
) -> int:
    """Get internal learning identifier, creating the learning if needed."""

    cursor.execute(
        "SELECT id FROM learnings WHERE user_id = %s AND learning_id = %s",
        (user_db_id, learning_id),
    )
    if row := cursor.fetchone():
        return int(row[0])
    cursor.execute(
        "INSERT INTO learnings (user_id, learning_id, name, "
        "learning_language, course_id) VALUES (%s, %s, %s, %s, %s) "
        "RETURNING id",
        (user_db_id, learning_id, name, language, course_db_id),
    )
    row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _get_lexicon_db_id(
    cursor: psycopg.Cursor, user_db_id: int, lexicon_id: str, language: str
) -> int:
    """Get internal lexicon identifier, creating the lexicon if needed."""

    cursor.execute(
        "SELECT id FROM lexicons WHERE user_id = %s AND lexicon_id = %s",
        (user_db_id, lexicon_id),
    )
    if row := cursor.fetchone():
        return int(row[0])
    cursor.execute(
        "INSERT INTO lexicons (user_id, lexicon_id, language) "
        "VALUES (%s, %s, %s) RETURNING id",
        (user_db_id, lexicon_id, language),
    )
    row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def load_learning(
    user_id: str, learning_id: str
) -> tuple[list[LearnRecordRow], list[LearnSessionRow]]:
    """Load all learning records and sessions of a user's learning.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    :return: (records, sessions) in insertion order; empty lists if the
        learning is not in the database
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT r.question_id, r.response, r.response_time, "
            "r.request_time, r.extra "
            "FROM learning_records r "
            "JOIN learnings l ON l.id = r.learning_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s ORDER BY r.id",
            (user_id, learning_id),
        )
        records: list[LearnRecordRow] = [
            (row[0], row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        ]
        cursor.execute(
            'SELECT s.type, s.start, s."end", s.actions '
            "FROM learning_sessions s "
            "JOIN learnings l ON l.id = s.learning_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s ORDER BY s.id",
            (user_id, learning_id),
        )
        sessions: list[LearnSessionRow] = [
            (row[0], row[1], row[2], row[3]) for row in cursor.fetchall()
        ]
    return records, sessions


def delete_last_learn_record(user_id: str, learning_id: str) -> str | None:
    """Delete the most recent answer in a learning and return its word.

    Undoes a single repetition answer. Learning keeps no per-word cache (its
    state is derived from the records on load), so only the record is removed.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    :return: the word whose answer was removed, or `None` if there is nothing
        to undo
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT r.id, r.question_id "
            "FROM learning_records r "
            "JOIN learnings l ON l.id = r.learning_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.learning_id = %s "
            "ORDER BY r.response_time DESC, r.id DESC LIMIT 1",
            (user_id, learning_id),
        )
        if not (row := cursor.fetchone()):
            return None
        record_id, question_id = row
        cursor.execute(
            "DELETE FROM learning_records WHERE id = %s", (record_id,)
        )
    return str(question_id)


def save_learning(
    user_id: str,
    learning_id: str,
    name: str,
    language: str,
    course_id: str,
    records: list[LearnRecordRow],
    sessions: list[LearnSessionRow],
) -> None:
    """Append learning records and sessions of a user's learning.

    :param user_id: owning user login, e.g. `john`
    :param learning_id: learning identifier, e.g. `fr`
    :param name: learning name, used if the learning is to be created
    :param language: learning language code, used if the learning is to be
        created
    :param course_id: identifier of the parent course, used if the learning
        is to be created; the course must already exist
    :param records: new records, not yet stored in the database
    :param sessions: new sessions, not yet stored in the database
    """
    with db_cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        course_db_id: int = _get_course_db_id(cursor, user_db_id, course_id)
        db_id: int = _get_learning_db_id(
            cursor, user_db_id, learning_id, name, language, course_db_id
        )
        cursor.executemany(
            "INSERT INTO learning_records (learning_id, question_id, "
            "response, response_time, request_time, extra) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (
                    db_id,
                    question_id,
                    response,
                    response_time,
                    request_time,
                    Jsonb(extra) if extra else None,
                )
                for (
                    question_id,
                    response,
                    response_time,
                    request_time,
                    extra,
                ) in records
            ],
        )
        cursor.executemany(
            "INSERT INTO learning_sessions "
            '(learning_id, type, start, "end", actions) '
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (db_id, type_, start, end, actions)
                for (type_, start, end, actions) in sessions
            ],
        )


def load_lexicon(
    user_id: str, lexicon_id: str
) -> tuple[list[LexiconRecordRow], list[LexiconSessionRow]]:
    """Load all lexicon records and sessions of a user.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: (records, sessions) in insertion order; empty lists if the
        lexicon is not in the database
    """
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT w.word, r.response, r.response_time, r.extra "
            "FROM lexicon_records r "
            "JOIN lexicon_words w ON w.id = r.word_id "
            "JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s ORDER BY r.id",
            (user_id, lexicon_id),
        )
        records: list[LexiconRecordRow] = [
            (row[0], row[1], row[2], row[3]) for row in cursor.fetchall()
        ]
        cursor.execute(
            'SELECT s.start, s."end" FROM lexicon_sessions s '
            "JOIN lexicons l ON l.id = s.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s ORDER BY s.id",
            (user_id, lexicon_id),
        )
        sessions: list[LexiconSessionRow] = [
            (row[0], row[1]) for row in cursor.fetchall()
        ]
    return records, sessions


def save_lexicon(
    user_id: str,
    lexicon_id: str,
    language: str,
    records: list[LexiconRecordRow],
    sessions: list[LexiconSessionRow],
) -> None:
    """Append lexicon records and sessions of a user.

    Word state (`lexicon_words.response`, `to_skip`, `last_seen`) is updated
    so that the last record wins, mirroring the in-memory behavior.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :param language: lexicon language code, used if the lexicon is to be
        created
    :param records: new records, not yet stored in the database
    :param sessions: new sessions, not yet stored in the database
    """
    with db_cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        db_id: int = _get_lexicon_db_id(
            cursor, user_db_id, lexicon_id, language
        )

        for word, response, response_time, extra in records:
            to_skip: bool | None = (extra or {}).get("sk")
            cursor.execute(
                "INSERT INTO lexicon_words "
                "(lexicon_id, word, response, to_skip, last_seen) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (lexicon_id, word) DO UPDATE SET "
                "response = excluded.response, to_skip = excluded.to_skip, "
                "last_seen = excluded.last_seen "
                "RETURNING id",
                (db_id, word, response, to_skip, response_time),
            )
            row = cursor.fetchone()
            assert row is not None
            cursor.execute(
                "INSERT INTO lexicon_records "
                "(word_id, response, response_time, extra) "
                "VALUES (%s, %s, %s, %s)",
                (
                    row[0],
                    response,
                    response_time,
                    Jsonb(extra) if extra else None,
                ),
            )

        cursor.executemany(
            'INSERT INTO lexicon_sessions (lexicon_id, start, "end") '
            "VALUES (%s, %s, %s)",
            [(db_id, start, end) for (start, end) in sessions],
        )
