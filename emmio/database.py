"""SQLite 3 utility."""

import sqlite3
from pathlib import Path
from sqlite3.dbapi2 import Connection, Cursor

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Database:
    """Pretty simple wrapper for SQLite database."""

    def __init__(self, database_file_path: Path):
        """
        :param database_file_path: path to SQLite database file
        """
        self.connection: Connection = sqlite3.connect(
            database_file_path, check_same_thread=False
        )
        self.cursor: Cursor = self.connection.cursor()

    def get_table_ids(self) -> list[str]:
        """Get identifiers of all tables in the database."""
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        return [x[0] for x in self.cursor.fetchall()]

    def has_table(self, table_id: str) -> bool:
        """Check whether table is in the database."""
        return table_id in self.get_table_ids()

    def drop_table(self, table_id: str) -> None:
        """Remove table from the database."""
        self.cursor.execute(f"DROP TABLE {table_id};")
