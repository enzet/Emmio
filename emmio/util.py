"""
Emmio.

Utility functions.

Author: Sergey Vartanov.
"""
import sqlite3
from datetime import datetime, timedelta
from sqlite3 import Connection
from typing import List


class Database:
    def __init__(self, data_base_file_name: str):
        database: Connection = sqlite3.connect(data_base_file_name)
        self.cursor = database.cursor()

    def get_table_ids(self) -> List[str]:
        self.cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table';")
        return self.cursor.fetchall()


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
