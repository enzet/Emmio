"""
Emmio.

Utility functions.
"""
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta

import urllib3
from pathlib import Path

from colour import Color
from urllib3 import PoolManager, HTTPResponse, Timeout

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

HIDE_SYMBOL: str = "░"


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


def format_delta(delta: timedelta):
    if delta < timedelta(hours=1):
        minutes: int = int(delta.total_seconds() // 60)
        return f"{minutes} minute" + ("s" if minutes > 1 else "")
    if delta < timedelta(days=1):
        hours: int = int(delta.total_seconds() // 60 // 60)
        return f"{hours} hour" + ("s" if hours > 1 else "")

    days: int = int(delta.total_seconds() // 60 // 60 // 24)
    return f"{days} day" + ("s" if days > 1 else "")


def download(
    address: str, cache_path: Path, buffer_size: int = 0x80000
) -> bytes | None:
    logging.info(f"Downloading {address}...")

    timeout = Timeout(connect=1.0, read=2.0)
    pool_manager: PoolManager = PoolManager(timeout=timeout)
    try:
        result: HTTPResponse = pool_manager.request(
            "GET", address, preload_content=False
        )
    except urllib3.exceptions.MaxRetryError:
        return None
    pool_manager.clear()
    data: bytearray = bytearray()
    while True:
        buffer: bytes = result.read(buffer_size)
        if not buffer:
            break
        data.extend(buffer)

    with cache_path.open("wb+") as temp_file:
        temp_file.write(data)

    return data


@dataclass
class MalformedFile(Exception):
    path: Path


@dataclass
class MalformedData(Exception):
    message: str


def remove_parenthesis(text: str) -> str:
    depth: int = 0
    result: str = ""

    for character in text:
        if character == "(":
            depth += 1
        if character == ")":
            depth -= 1
            continue
        if depth == 0:
            result += character

    return result.strip()


def flatten(
    array: list[list[list[str]]],
    limit_1: int,
    limit_2: int,
    limit_3: int,
) -> str:
    result: str = ""
    for i in array[:limit_1]:
        for j in i[:limit_2]:
            result += ("; " if result else "") + ", ".join(j[:limit_3])
    return result


def get_color(prompt) -> Color:
    return Color("#" + str(hex(abs(hash(prompt))))[2:8])
