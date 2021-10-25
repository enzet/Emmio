"""
SQLite 3 utility.
"""
import sqlite3
from sqlite3.dbapi2 import Connection, Cursor
from typing import List

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"


class Database:
    """
    Pretty simple wrapper for SQLite database.
    """

    def __init__(self, database_file_name: str):
        """
        :param database_file_name: SQLite database file name
        """
        self.connection: Connection = sqlite3.connect(database_file_name)
        self.cursor: Cursor = self.connection.cursor()

    def get_table_ids(self) -> List[str]:
        """Get identifiers of all tables in the database."""
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
        return [x[0] for x in self.cursor.fetchall()]

    def has_table(self, table_id: str) -> bool:
        """Check whether table is in the database."""
        return table_id in self.get_table_ids()
