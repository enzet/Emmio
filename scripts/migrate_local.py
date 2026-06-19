"""One-time migration of local JSON user data to PostgreSQL.

Reads learning and lexicon data referenced by the user configuration file
(`<data dir>/users/<user>/config.json`) and writes it into the PostgreSQL
database created with `scripts/schema.sql`.

Usage:

    python scripts/migrate_local.py --user enzet

The database connection string is taken from the `DATABASE_URL` environment
variable or the `--dsn` option (default: `postgresql:///emmio`).
"""

import argparse
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, LiteralString

import psycopg
from psycopg.types.json import Jsonb

from emmio.learn.core import load_old_format
from emmio.postgres import learn_config_jsonb, split_lexicon_config

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

logger: logging.Logger = logging.getLogger(__name__)

LEXICON_RESPONSE_CODES: dict[str, str] = {
    "know": "K",
    "dont": "D",
    "not_a_word": "N",
    "dont_but_proper_noun_too": "B",
    "know_or_not_a_word": "?",
    "unknown": "U",
}

# `user_answer` and `unknown` map to no key at all: absent means user answer.
ANSWER_TYPE_CODES: dict[str, str] = {
    "assume_not_a_word": "aa",
    "assume_not_a_word_dict": "ad",
    "propagate_skip": "ps",
    "propagate_not_a_word": "pn",
    "propagate_time": "pt",
}

TRUNCATE_STATEMENT: LiteralString = (
    "TRUNCATE users, learn_records, learn_sessions, learn_courses, "
    "lexicon_records, lexicon_words, lexicon_sessions, lexicons "
    "RESTART IDENTITY CASCADE"
)


def parse_time(value: str) -> datetime:
    """Parse ISO timestamp, assuming UTC when the time zone is missing."""

    time: datetime = datetime.fromisoformat(value)
    if time.tzinfo is None:
        time = time.replace(tzinfo=UTC)
    return time


def load_learn_records(path: Path) -> tuple[list[dict], list[dict]]:
    """Load learning records and sessions from a JSON or YAML file.

    :param path: path to the learning process file
    :return: (records, sessions), records as dictionaries with `question_id`,
        `response`, `sentence_id`, `time`, `request_time` keys
    """
    if path.suffix == ".json":
        with path.open(encoding="utf-8") as input_file:
            data: dict[str, Any] = json.load(input_file)
        return data.get("records", []), data.get("sessions", [])

    if path.suffix == ".yml":
        # Old experimental format, loaded through the existing Emmio code.
        process = load_old_format(path)
        records: list[dict] = [
            {
                "question_id": record.question_id,
                "response": record.response.value,
                "sentence_id": record.sentence_id,
                "time": record.time.isoformat(),
            }
            for record in process.records
        ]
        return records, []

    message: str = f"Unknown learning file format: `{path.name}`."
    raise ValueError(message)


def migrate_learning(
    cursor: psycopg.Cursor,
    user_db_id: int,
    course_id: str,
    config: dict,
    path: Path,
) -> tuple[int, int]:
    """Migrate one learning course.

    :param cursor: database cursor
    :param user_db_id: internal identifier of the owning user
    :param course_id: course identifier (key in the user configuration)
    :param config: course configuration
    :param path: path to the user `learn` directory
    :return: (number of records, number of sessions) migrated
    """
    file_path: Path = path / config["file_name"]
    records: list[dict] = []
    sessions: list[dict] = []
    if file_path.exists():
        records, sessions = load_learn_records(file_path)
    else:
        logger.warning("File `%s` does not exist, skipping.", file_path)

    cursor.execute(
        "INSERT INTO learn_courses (user_id, course_id, name, "
        "learning_language, config) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (
            user_db_id,
            course_id,
            config.get("name", course_id),
            config["learning_language"],
            Jsonb(learn_config_jsonb(config)),
        ),
    )
    row = cursor.fetchone()
    assert row is not None
    internal_id: int = row[0]

    record_rows: list[tuple] = []
    for record in records:
        extra: dict[str, Any] = {}
        if record.get("sentence_id"):
            extra["si"] = record["sentence_id"]
        record_rows.append(
            (
                internal_id,
                record["question_id"],
                record["response"],
                parse_time(record["time"]),
                (
                    parse_time(record["request_time"])
                    if record.get("request_time")
                    else None
                ),
                Jsonb(extra) if extra else None,
            )
        )
    cursor.executemany(
        "INSERT INTO learn_records "
        "(course_id, question_id, response, response_time, request_time, "
        "extra) VALUES (%s, %s, %s, %s, %s, %s)",
        record_rows,
    )

    session_rows: list[tuple] = [
        (
            internal_id,
            session["type"],
            parse_time(session["start"]),
            parse_time(session["end"]) if session.get("end") else None,
            session.get("actions"),
        )
        for session in sessions
    ]
    cursor.executemany(
        'INSERT INTO learn_sessions (course_id, type, start, "end", actions) '
        "VALUES (%s, %s, %s, %s, %s)",
        session_rows,
    )
    return len(record_rows), len(session_rows)


def migrate_lexicon(
    cursor: psycopg.Cursor,
    user_db_id: int,
    lexicon_id: str,
    config: dict,
    path: Path,
) -> tuple[int, int]:
    """Migrate one lexicon.

    :param cursor: database cursor
    :param user_db_id: internal identifier of the owning user
    :param lexicon_id: lexicon identifier (key in the user configuration)
    :param config: lexicon configuration
    :param path: path to the user `lexicon` directory
    :return: (number of records, number of sessions) migrated
    """
    file_path: Path = path / config["file_name"]
    records: list[dict] = []
    sessions: list[dict] = []
    if file_path.exists():
        with file_path.open(encoding="utf-8") as input_file:
            data: dict[str, Any] = json.load(input_file)
        records = data.get("records", [])
        sessions = data.get("sessions", [])
    else:
        logger.warning("File `%s` does not exist, skipping.", file_path)

    # Split configuration by tier (see research/app.md), reusing the same
    # logic the runtime uses.
    selection, identity_list, mutable_config = split_lexicon_config(config)

    cursor.execute(
        "INSERT INTO lexicons (user_id, lexicon_id, language, selection, "
        "frequency_list, config) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            user_db_id,
            lexicon_id,
            config["language"],
            selection,
            Jsonb(identity_list) if identity_list else None,
            Jsonb(mutable_config),
        ),
    )
    row = cursor.fetchone()
    assert row is not None
    internal_id: int = row[0]

    # Insert words first; keep current state of each word (last record wins).
    word_ids: dict[str, int] = {}
    word_state: dict[str, tuple[str, bool | None, datetime]] = {}
    for record in records:
        word: str = record["word"]
        response: str = LEXICON_RESPONSE_CODES[record["response"]]
        word_state[word] = (
            response,
            record.get("to_skip"),
            parse_time(record["time"]),
        )
    for word, (response, to_skip, last_seen) in word_state.items():
        cursor.execute(
            "INSERT INTO lexicon_words "
            "(lexicon_id, word, response, to_skip, last_seen) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (internal_id, word, response, to_skip, last_seen),
        )
        row = cursor.fetchone()
        assert row is not None
        word_ids[word] = row[0]

    record_rows: list[tuple] = []
    for record in records:
        extra = {}
        answer_type: str | None = record.get("answer_type")
        if answer_type in ANSWER_TYPE_CODES:
            extra["at"] = ANSWER_TYPE_CODES[answer_type]
        if record.get("to_skip") is not None:
            extra["sk"] = record["to_skip"]
        if record.get("request_time"):
            extra["rt"] = record["request_time"]
        record_rows.append(
            (
                word_ids[record["word"]],
                LEXICON_RESPONSE_CODES[record["response"]],
                parse_time(record["time"]),
                Jsonb(extra) if extra else None,
            )
        )
    cursor.executemany(
        "INSERT INTO lexicon_records (word_id, response, response_time, "
        "extra) VALUES (%s, %s, %s, %s)",
        record_rows,
    )

    session_rows: list[tuple] = [
        (
            internal_id,
            parse_time(session["start"]),
            parse_time(session["end"]) if session.get("end") else None,
        )
        for session in sessions
    ]
    cursor.executemany(
        'INSERT INTO lexicon_sessions (lexicon_id, start, "end") '
        "VALUES (%s, %s, %s)",
        session_rows,
    )
    return len(record_rows), len(session_rows)


def main() -> None:
    """Run the migration."""

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__
    )
    parser.add_argument("--user", required=True, help="user identifier")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".emmio",
        help="path to Emmio data directory",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", "postgresql:///emmio"),
        help="PostgreSQL connection string",
    )
    arguments: argparse.Namespace = parser.parse_args()

    user_path: Path = arguments.data_dir / "users" / arguments.user
    with (user_path / "config.json").open(encoding="utf-8") as config_file:
        user_config: dict[str, Any] = json.load(config_file)

    with psycopg.connect(arguments.dsn) as connection:
        with connection.cursor() as cursor:
            # Make the migration idempotent: start from empty tables.
            cursor.execute(TRUNCATE_STATEMENT)

            # Create the owning user and remember its internal identifier.
            cursor.execute(
                "INSERT INTO users (user_id, name) VALUES (%s, %s) "
                "RETURNING id",
                (arguments.user, user_config.get("name", arguments.user)),
            )
            user_row = cursor.fetchone()
            assert user_row is not None
            user_db_id: int = user_row[0]
            logger.info("User `%s` created.", arguments.user)

            for course_id, config in user_config.get("learn", {}).items():
                records, sessions = migrate_learning(
                    cursor, user_db_id, course_id, config, user_path / "learn"
                )
                logger.info(
                    "Learning `%s`: %d records, %d sessions.",
                    course_id,
                    records,
                    sessions,
                )

            for lexicon_id, config in user_config.get("lexicon", {}).items():
                records, sessions = migrate_lexicon(
                    cursor,
                    user_db_id,
                    lexicon_id,
                    config,
                    user_path / "lexicon",
                )
                logger.info(
                    "Lexicon `%s`: %d records, %d sessions.",
                    lexicon_id,
                    records,
                    sessions,
                )

        connection.commit()

    logger.info("Migration finished.")


if __name__ == "__main__":
    main()
