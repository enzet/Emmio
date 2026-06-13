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


def _get_course_db_id(
    cursor: psycopg.Cursor, course_id: str, name: str, language: str
) -> int:
    """Get internal course identifier, creating the course if needed."""

    cursor.execute(
        "SELECT id FROM learn_courses WHERE course_id = %s", (course_id,)
    )
    if row := cursor.fetchone():
        return int(row[0])
    cursor.execute(
        "INSERT INTO learn_courses (course_id, name, learning_language) "
        "VALUES (%s, %s, %s) RETURNING id",
        (course_id, name, language),
    )
    row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def _get_lexicon_db_id(
    cursor: psycopg.Cursor, lexicon_id: str, language: str
) -> int:
    """Get internal lexicon identifier, creating the lexicon if needed."""

    cursor.execute(
        "SELECT id FROM lexicons WHERE lexicon_id = %s", (lexicon_id,)
    )
    if row := cursor.fetchone():
        return int(row[0])
    cursor.execute(
        "INSERT INTO lexicons (lexicon_id, language) VALUES (%s, %s) "
        "RETURNING id",
        (lexicon_id, language),
    )
    row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def load_learning(
    course_id: str,
) -> tuple[list[LearnRecordRow], list[LearnSessionRow]]:
    """Load all learning records and sessions of a course.

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
            "WHERE c.course_id = %s ORDER BY r.id",
            (course_id,),
        )
        records: list[LearnRecordRow] = [
            (row[0], row[1], row[2], row[3], row[4])
            for row in cursor.fetchall()
        ]
        cursor.execute(
            'SELECT s.type, s.start, s."end", s.actions '
            "FROM learn_sessions s "
            "JOIN learn_courses c ON c.id = s.course_id "
            "WHERE c.course_id = %s ORDER BY s.id",
            (course_id,),
        )
        sessions: list[LearnSessionRow] = [
            (row[0], row[1], row[2], row[3]) for row in cursor.fetchall()
        ]
    return records, sessions


def save_learning(
    course_id: str,
    name: str,
    language: str,
    records: list[LearnRecordRow],
    sessions: list[LearnSessionRow],
) -> None:
    """Append learning records and sessions of a course.

    :param course_id: course identifier, e.g. `fr`
    :param name: course name, used if the course is to be created
    :param language: learning language code, used if the course is to be
        created
    :param records: new records, not yet stored in the database
    :param sessions: new sessions, not yet stored in the database
    """
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
        db_id: int = _get_course_db_id(cursor, course_id, name, language)
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
    lexicon_id: str,
) -> tuple[list[LexiconRecordRow], list[LexiconSessionRow]]:
    """Load all lexicon records and sessions.

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
            "WHERE l.lexicon_id = %s ORDER BY r.id",
            (lexicon_id,),
        )
        records: list[LexiconRecordRow] = [
            (row[0], row[1], row[2], row[3]) for row in cursor.fetchall()
        ]
        cursor.execute(
            'SELECT s.start, s."end" FROM lexicon_sessions s '
            "JOIN lexicons l ON l.id = s.lexicon_id "
            "WHERE l.lexicon_id = %s ORDER BY s.id",
            (lexicon_id,),
        )
        sessions: list[LexiconSessionRow] = [
            (row[0], row[1]) for row in cursor.fetchall()
        ]
    return records, sessions


def save_lexicon(
    lexicon_id: str,
    language: str,
    records: list[LexiconRecordRow],
    sessions: list[LexiconSessionRow],
) -> None:
    """Append lexicon records and sessions.

    Word state (`lexicon_words.response`, `to_skip`, `last_seen`) is updated
    so that the last record wins, mirroring the in-memory behavior.

    :param lexicon_id: lexicon identifier, e.g. `fr`
    :param language: lexicon language code, used if the lexicon is to be
        created
    :param records: new records, not yet stored in the database
    :param sessions: new sessions, not yet stored in the database
    """
    connection: psycopg.Connection = get_connection()
    with connection.cursor() as cursor:
        db_id: int = _get_lexicon_db_id(cursor, lexicon_id, language)

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
