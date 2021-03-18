"""
Emmio.

Utility functions.

Author: Sergey Vartanov.
"""
from datetime import datetime, timedelta


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
