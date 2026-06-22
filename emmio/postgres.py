"""PostgreSQL storage for user learning and lexicon data.

This module is model-agnostic: it accepts and returns plain values, and the
conversion to and from Emmio data structures happens in `emmio.learn.core`
and `emmio.lexicon.core`. See `scripts/schema.sql` for the table definitions
and the `extra` JSONB key dictionaries.

The connection string is taken from the `EMMIO_DATABASE_URL` or
`DATABASE_URL` environment variable (default: `postgresql:///emmio`).
"""

import os
from datetime import datetime

import psycopg
from psycopg.types.json import Jsonb

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
    {"frequency", "logistic", "stratified", "binary_search", "threshold"}
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
    if config.get("dictionaries"):
        mutable["dictionaries"] = config["dictionaries"]
    if config.get("sentences"):
        mutable["sentences"] = config["sentences"]
    if config.get("precision_per_week"):
        mutable["precision_per_week"] = config["precision_per_week"]
    if not is_sampling and frequency_list:
        mutable["frequency_lists"] = [frequency_list]

    return selection, identity_list, mutable


_connection: psycopg.Connection | None = None


def get_connection() -> psycopg.Connection:
    """Get the global database connection, creating it on first use."""

    global _connection  # noqa: PLW0603  # pylint: disable=global-statement

    if _connection is None:
        dsn: str = os.environ.get(
            "EMMIO_DATABASE_URL", os.environ.get("DATABASE_URL", DEFAULT_DSN)
        )
        # Always read timestamps as UTC, regardless of the machine time zone,
        # so that loaded data and JSON exports are deterministic.
        _connection = psycopg.connect(dsn, options="-c timezone=UTC")
    return _connection


def ensure_user(user_id: str, name: str) -> None:
    """Create the user if it does not exist yet.

    :param user_id: stable string login, e.g. `john`
    :param name: display name
    """
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO users (user_id, name) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, name),
        )
    connection.commit()


def user_exists(user_id: str) -> bool:
    """Check whether a user with the given login exists."""

    with get_connection().cursor() as cursor:
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
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
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
    connection.commit()


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
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
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
    connection.commit()


def get_credentials_by_email(email: str) -> tuple[str, str] | None:
    """Get (user login, password hash) for an email, or `None` if not found.

    Only users registered with a password (via the API) are returned; CLI-only
    users have no password and cannot log in.

    :param email: email address to look up
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT user_id, hashed_password FROM users "
            "WHERE email = %s AND hashed_password IS NOT NULL",
            (email,),
        )
        if row := cursor.fetchone():
            return row[0], row[1]
        return None


def list_users() -> list[tuple[str, str]]:
    """Get all users as (login, display name) pairs, ordered by login."""

    with get_connection().cursor() as cursor:
        cursor.execute("SELECT user_id, name FROM users ORDER BY user_id")
        return [(row[0], row[1]) for row in cursor.fetchall()]


def list_courses(user_id: str) -> list[tuple[str, str, str, int, int]]:
    """Get a user's courses with short info.

    :param user_id: owning user login, e.g. `john`
    :return: (course id, name, learning language, distinct words studied,
        total answers) tuples, ordered by course id
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT c.course_id, c.name, c.learning_language, "
            "(SELECT count(DISTINCT r.question_id) FROM learn_records r "
            "WHERE r.course_id = c.id), "
            "(SELECT count(*) FROM learn_records r WHERE r.course_id = c.id) "
            "FROM learn_courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s ORDER BY c.course_id",
            (user_id,),
        )
        return [
            (row[0], row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        ]


def list_lexicons(user_id: str) -> list[tuple[str, str, str | None, int, int]]:
    """Get a user's lexicons with short info.

    :param user_id: owning user login, e.g. `john`
    :return: (lexicon id, language, selection strategy, number of words
        checked, number of "don't know" answers in the last 7 days) tuples,
        ordered by lexicon id
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT l.lexicon_id, l.language, l.selection, "
            "(SELECT count(*) FROM lexicon_words w "
            "WHERE w.lexicon_id = l.id), "
            "(SELECT count(*) FROM lexicon_records r "
            "JOIN lexicon_words w2 ON w2.id = r.word_id "
            "WHERE w2.lexicon_id = l.id AND r.response = 'D' "
            "AND r.response_time >= now() - interval '7 days') "
            "FROM lexicons l JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s ORDER BY l.lexicon_id",
            (user_id,),
        )
        return [
            (row[0], row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        ]


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
    with get_connection().cursor() as cursor:
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
        "frequency_list": frequency_list,
        "dictionaries": config.get("dictionaries"),
        "sentences": config.get("sentences"),
        "precision_per_week": config.get("precision_per_week", 0),
    }


def get_lexicon_config(user_id: str, lexicon_id: str) -> dict | None:
    """Get a lexicon's reassembled config dict, or `None` if it does not exist.

    The dict matches the `LexiconConfig` fields (language, selection,
    frequency_list, dictionaries, sentences, precision_per_week).

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    """
    with get_connection().cursor() as cursor:
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
    with get_connection().cursor() as cursor:
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
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
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
    connection.commit()


LEARN_CONFIG_KEYS: tuple[str, ...] = (
    "base_languages",
    "is_active",
    "scheme",
    "sentences",
    "dictionaries",
    "audio",
    "check_lexicon",
    "ask_lexicon",
    "max_for_day",
)
"""Mutable `LearnConfig` fields stored in the `config` JSONB.

Identity fields (`name`, `learning_language`) are columns instead.
"""


def learn_config_jsonb(config: dict) -> dict:
    """Extract the mutable part of a flat learn configuration for storage.

    :param config: flat learn configuration (the `LearnConfig` fields)
    :return: the subset stored in the `config` JSONB column
    """
    return {key: config[key] for key in LEARN_CONFIG_KEYS if key in config}


def _assemble_learn_config(
    name: str, learning_language: str, config: dict | None
) -> dict:
    """Build a flat learn configuration from the database columns plus JSONB."""
    return {
        "name": name,
        "learning_language": learning_language,
        **(config or {}),
    }


def get_learn_config(user_id: str, course_id: str) -> dict | None:
    """Get a course's reassembled configuration dictionary.

    Return `None` if it does not exist.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `fr`
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT c.name, c.learning_language, c.config "
            "FROM learn_courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s AND c.course_id = %s",
            (user_id, course_id),
        )
        if row := cursor.fetchone():
            return _assemble_learn_config(row[0], row[1], row[2])
        return None


def get_learn_configs(user_id: str) -> dict[str, dict]:
    """Get reassembled configuration dictionaries for all of a user's courses.

    :param user_id: owning user login, e.g. `john`
    :return: mapping from course identifier to its config dict
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT c.course_id, c.name, c.learning_language, c.config "
            "FROM learn_courses c JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s ORDER BY c.course_id",
            (user_id,),
        )
        return {
            row[0]: _assemble_learn_config(row[1], row[2], row[3])
            for row in cursor.fetchall()
        }


def store_learn_config(user_id: str, course_id: str, config: dict) -> None:
    """Create or update a course's configuration.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `fr`
    :param config: flat learn config (the `LearnConfig` fields)
    """
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        cursor.execute(
            "INSERT INTO learn_courses "
            "(user_id, course_id, name, learning_language, config) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (user_id, course_id) DO UPDATE SET "
            "name = excluded.name, "
            "learning_language = excluded.learning_language, "
            "config = excluded.config",
            (
                user_db_id,
                course_id,
                config["name"],
                config["learning_language"],
                Jsonb(learn_config_jsonb(config)),
            ),
        )
    connection.commit()


def get_answered_words(user_id: str, lexicon_id: str) -> set[str]:
    """Get the set of words already recorded in a user's lexicon.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT w.word "
            "FROM lexicon_words w JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s",
            (user_id, lexicon_id),
        )
        return {row[0] for row in cursor.fetchall()}


def get_words_to_skip(
    user_id: str, lexicon_id: str, recent_days: int = 30
) -> set[str]:
    """Get words to exclude when picking the next word to check.

    A frequency lexicon re-samples words over time, so a word is only excluded
    if it is flagged to skip or was answered within the last `recent_days`
    days; everything else stays selectable (mirrors the CLI's checking loop).

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :param recent_days: re-ask an answered word only after this many days
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT w.word "
            "FROM lexicon_words w JOIN lexicons l ON l.id = w.lexicon_id "
            "JOIN users u ON u.id = l.user_id "
            "WHERE u.user_id = %s AND l.lexicon_id = %s "
            "AND (w.to_skip = true "
            "OR w.last_seen >= now() - make_interval(days => %s))",
            (user_id, lexicon_id, recent_days),
        )
        return {row[0] for row in cursor.fetchall()}


def _get_user_db_id(cursor: psycopg.Cursor, user_id: str) -> int:
    """Get internal user identifier, raising if the user does not exist."""

    cursor.execute("SELECT id FROM users WHERE user_id = %s", (user_id,))
    if row := cursor.fetchone():
        return int(row[0])
    message: str = f"Unknown user `{user_id}`; create it first."
    raise ValueError(message)


def _get_course_db_id(
    cursor: psycopg.Cursor,
    user_db_id: int,
    course_id: str,
    name: str,
    language: str,
) -> int:
    """Get internal course identifier, creating the course if needed."""

    cursor.execute(
        "SELECT id FROM learn_courses WHERE user_id = %s AND course_id = %s",
        (user_db_id, course_id),
    )
    if row := cursor.fetchone():
        return int(row[0])
    cursor.execute(
        "INSERT INTO learn_courses (user_id, course_id, name, "
        "learning_language) VALUES (%s, %s, %s, %s) RETURNING id",
        (user_db_id, course_id, name, language),
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
    user_id: str, course_id: str
) -> tuple[list[LearnRecordRow], list[LearnSessionRow]]:
    """Load all learning records and sessions of a user's course.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `fr`
    :return: (records, sessions) in insertion order; empty lists if the
        course is not in the database
    """
    with get_connection().cursor() as cursor:
        cursor.execute(
            "SELECT r.question_id, r.response, r.response_time, "
            "r.request_time, r.extra "
            "FROM learn_records r "
            "JOIN learn_courses c ON c.id = r.course_id "
            "JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s AND c.course_id = %s ORDER BY r.id",
            (user_id, course_id),
        )
        records: list[LearnRecordRow] = [
            (row[0], row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        ]
        cursor.execute(
            'SELECT s.type, s.start, s."end", s.actions '
            "FROM learn_sessions s "
            "JOIN learn_courses c ON c.id = s.course_id "
            "JOIN users u ON u.id = c.user_id "
            "WHERE u.user_id = %s AND c.course_id = %s ORDER BY s.id",
            (user_id, course_id),
        )
        sessions: list[LearnSessionRow] = [
            (row[0], row[1], row[2], row[3]) for row in cursor.fetchall()
        ]
    return records, sessions


def save_learning(
    user_id: str,
    course_id: str,
    name: str,
    language: str,
    records: list[LearnRecordRow],
    sessions: list[LearnSessionRow],
) -> None:
    """Append learning records and sessions of a user's course.

    :param user_id: owning user login, e.g. `john`
    :param course_id: course identifier, e.g. `fr`
    :param name: course name, used if the course is to be created
    :param language: learning language code, used if the course is to be
        created
    :param records: new records, not yet stored in the database
    :param sessions: new sessions, not yet stored in the database
    """
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
        user_db_id: int = _get_user_db_id(cursor, user_id)
        db_id: int = _get_course_db_id(
            cursor, user_db_id, course_id, name, language
        )
        cursor.executemany(
            "INSERT INTO learn_records (course_id, question_id, response, "
            "response_time, request_time, extra) "
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
            "INSERT INTO learn_sessions "
            '(course_id, type, start, "end", actions) '
            "VALUES (%s, %s, %s, %s, %s)",
            [
                (db_id, type_, start, end, actions)
                for (type_, start, end, actions) in sessions
            ],
        )
    connection.commit()


def load_lexicon(
    user_id: str, lexicon_id: str
) -> tuple[list[LexiconRecordRow], list[LexiconSessionRow]]:
    """Load all lexicon records and sessions of a user.

    :param user_id: owning user login, e.g. `john`
    :param lexicon_id: lexicon identifier, e.g. `fr`
    :return: (records, sessions) in insertion order; empty lists if the
        lexicon is not in the database
    """
    with get_connection().cursor() as cursor:
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
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
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
    connection.commit()


def close_connection() -> None:
    """Close the global connection if it is open."""

    global _connection  # noqa: PLW0603  # pylint: disable=global-statement

    if _connection is not None:
        _connection.close()
        _connection = None
