"""SQLite 3 utility."""

import sqlite3
import threading
from pathlib import Path
from sqlite3.dbapi2 import Connection

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Database:
    """Pretty simple wrapper for SQLite database.

    The database object is shared across threads (sync FastAPI endpoints run in
    a threadpool), but a single SQLite connection is not safe for concurrent
    use: sharing one connection or cursor across threads raises "Recursive use
    of cursors not allowed" or returns corrupted rows. Each thread therefore
    gets its own connection, created lazily and kept in thread-local storage.
    """

    def __init__(self, database_file_path: Path) -> None:
        """Initialize database.

        :param database_file_path: path to SQLite database file
        """
        self._database_file_path: Path = database_file_path
        self._local: threading.local = threading.local()

    @property
    def connection(self) -> Connection:
        """Get this thread's connection, opening one on first use."""
        connection: Connection | None = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self._database_file_path)
            self._local.connection = connection
        return connection

    def get_table_ids(self) -> list[str]:
        """Get identifiers of all tables in the database."""

        cursor = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        return [x[0] for x in cursor.fetchall()]

    def has_table(self, table_id: str) -> bool:
        """Check whether table is in the database."""
        return table_id in self.get_table_ids()
