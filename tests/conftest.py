"""Pytest configuration.

Tests must never touch the main Emmio database, so the connection is pointed
at the `emmio_test` database before any Emmio module creates it. The test
database is cleaned before every test.
"""

import os
from typing import LiteralString

import pytest

os.environ["EMMIO_DATABASE_URL"] = "postgresql:///emmio_test"

# The imports have to happen after the environment variable is set, so that
# the lazily created global connection uses the test database.
from emmio import postgres  # pylint: disable=wrong-import-position
from emmio.api.sessions import (  # pylint: disable=wrong-import-position
    LEARNING_REGISTRY,
    LEXICON_SESSIONS,
)

CLEAN_STATEMENT: LiteralString = (
    "TRUNCATE users, learning_records, learning_sessions, learnings, "
    "courses, lexicon_records, lexicon_words, lexicon_sessions, lexicons, "
    "curated_word_records, curated_words, curated_lists, "
    "language_knowledge_records "
    "RESTART IDENTITY CASCADE"
)


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Empty the test database before every test."""

    with postgres.db_connection() as connection, connection.cursor() as cursor:
        cursor.execute(CLEAN_STATEMENT)


@pytest.fixture(autouse=True)
def clean_registries() -> None:
    """Drop server-side session working memory before every test.

    The registries cache per-user state across requests; with the database
    truncated between tests, a stale cache would leak one test's state into
    the next.
    """
    LEXICON_SESSIONS.reset()
    LEARNING_REGISTRY.reset()
