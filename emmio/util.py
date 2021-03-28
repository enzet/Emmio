"""
Emmio.

Utility functions.

Author: Sergey Vartanov.
"""
import sqlite3
from datetime import datetime, timedelta
from sqlite3 import Connection, Cursor
from typing import List


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
        """ Get identifiers of all tables in the database. """
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';")
        return [x[0] for x in self.cursor.fetchall()]

    def has_table(self, table_id: str) -> bool:
        """ Check whether table is in the database. """
        return table_id in self.get_table_ids()


def day_start(point: datetime) -> datetime:
    return datetime(year=point.year, month=point.month, day=point.day)


def day_end(point: datetime) -> datetime:
    return day_start(point) + timedelta(days=1)


def year_start(point: datetime) -> datetime:
    return datetime(year=point.year, month=1, day=1)


def year_end(point: datetime) -> datetime:
    return datetime(year=point.year + 1, month=1, day=1)


def first_day_of_month(point: datetime) -> datetime:
    return datetime(year=point.year, month=point.month, day=1)


def plus_month(point: datetime) -> datetime:
    new_year = point.year
    new_month = point.month + 1
    if new_month > 12:
        new_month = 1
        new_year = point.year + 1
    return datetime(year=new_year, month=new_month, day=1)


def first_day_of_week(point: datetime) -> datetime:
    day = point.date() - timedelta(days=point.weekday())
    return datetime.combine(day, datetime.min.time())
