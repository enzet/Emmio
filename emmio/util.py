"""
Emmio.

Utility functions.
"""
import sys
from datetime import datetime, timedelta

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

from pathlib import Path

from urllib3 import PoolManager, HTTPResponse


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


def download(
    address: str, cache_path: Path, buffer_size: int = 400_000
) -> bytes:

    sys.stdout.write(f"Downloading {address}: ")
    sys.stdout.flush()

    pool_manager: PoolManager = PoolManager()
    result: HTTPResponse = pool_manager.request(
        "GET", address, preload_content=False
    )
    pool_manager.clear()
    data: bytearray = bytearray()
    while True:
        buffer: bytes = result.read(buffer_size)
        if not buffer:
            break
        sys.stdout.write("█")
        sys.stdout.flush()
        data.extend(buffer)
    sys.stdout.write("\n")

    with cache_path.open("wb+") as temp_file:
        temp_file.write(data)

    return data
