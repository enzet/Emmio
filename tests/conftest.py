"""Pytest configuration.

Tests must never touch the main Emmio database, so the connection is pointed
at the `emmio_test` database before any Emmio module creates it. The test
database is cleaned before every test.

The same goes for the data directory: it is pointed at an empty temporary
directory, so that a test can neither read the developer's own frequency
lists, dictionaries and caches (which a continuous integration runner does
not have anyway) nor write into them.
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from typing import LiteralString

import pytest

os.environ["EMMIO_DATABASE_URL"] = "postgresql:///emmio_test"

# The stand-in data directory has to exist: `ArtifactData.read_config` creates
# the artifact subdirectories it needs, but fails with `FileExistsError` if
# their parent is missing.
os.environ["EMMIO_DATA_DIR"] = tempfile.mkdtemp(prefix="emmio-test-data-")

# The imports have to happen after the environment variables are set, so that
# the lazily created global connection uses the test database. Only
# `os.environ` may be touched before them; anything else makes Ruff flag the
# imports as E402.
from emmio import postgres  # pylint: disable=wrong-import-position
from emmio.api.app import (
    reset_rate_limiters,  # pylint: disable=wrong-import-position
)
from emmio.api.sessions import (  # pylint: disable=wrong-import-position
    LEARNING_REGISTRY,
    LEXICON_SESSIONS,
)

DATA_DIRECTORY: str = os.environ["EMMIO_DATA_DIR"]
"""Stand-in for the Emmio data directory, thrown away after the run."""

CLEAN_STATEMENT: LiteralString = (
    "TRUNCATE users, learning_records, learning_sessions, learnings, "
    "courses, lexicon_records, lexicon_words, lexicon_sessions, lexicons, "
    "curated_word_records, curated_words, curated_lists, "
    "language_knowledge_records, user_languages "
    "RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session", autouse=True)
def remove_data_directory() -> Iterator[None]:
    """Remove the temporary data directory once the whole run is over."""

    yield
    shutil.rmtree(DATA_DIRECTORY, ignore_errors=True)


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
    reset_rate_limiters()
