"""Pytest configuration.

Tests must never touch the main Emmio database, so the connection is pointed
at the `emmio_test` database before any Emmio module creates it. The test
database is cleaned before every test.
"""

import os

import pytest

os.environ["EMMIO_DATABASE_URL"] = "postgresql:///emmio_test"

# The import has to happen after the environment variable is set, so that the
# lazily created global connection uses the test database.
from emmio import postgres  # pylint: disable=wrong-import-position

CLEAN_STATEMENT: str = (
    "TRUNCATE users, learn_records, learn_sessions, learn_courses, "
    "lexicon_records, lexicon_words, lexicon_sessions, lexicons "
    "RESTART IDENTITY CASCADE"
)


@pytest.fixture(autouse=True)
def clean_database() -> None:
    """Empty the test database before every test."""

    connection = postgres.get_connection()
    with connection.cursor() as cursor:
        cursor.execute(CLEAN_STATEMENT)
    connection.commit()
