"""Utility functions."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import urllib3
from colour import Color
from urllib3 import BaseHTTPResponse, PoolManager, Timeout

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

HIDE_SYMBOL: str = "░"


def write_atomic(path: Path, data: str) -> None:
    """Write data to a file atomically."""

    # Write to a temporary file.
    temp_path: Path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w+", encoding="utf-8") as output_file:
        output_file.write(data)

    # Atomically move the temporary file to the target path.
    temp_path.rename(path)


def day_start(point: datetime) -> datetime:
    """Get the start point of the day."""
    return datetime(year=point.year, month=point.month, day=point.day)


def day_end(point: datetime) -> datetime:
    """Get the end point of the day."""
    return day_start(point) + timedelta(days=1)


def year_start(point: datetime) -> datetime:
    """Get the start point of the year."""
    return datetime(year=point.year, month=1, day=1)


def year_end(point: datetime) -> datetime:
    """Get the end point of the year."""
    return datetime(year=point.year + 1, month=1, day=1)


def plus_year(point: datetime) -> datetime:
    """Get the point one year after the specified point."""
    new_year: int = point.year + 1
    day: datetime = datetime(year=new_year, month=1, day=1)
    return datetime.combine(day, point.time())


def month_start(point: datetime) -> datetime:
    """Get the start point of the month."""
    return datetime(year=point.year, month=point.month, day=1)


def plus_month(point: datetime) -> datetime:
    """Get the point one month after the specified point."""
    new_year: int = point.year
    new_month: int = point.month + 1
    if new_month > 12:
        new_month = 1
        new_year = point.year + 1
    day: datetime = datetime(year=new_year, month=new_month, day=1)
    return datetime.combine(day, point.time())


def week_start(point: datetime) -> datetime:
    """Get the start point of the week."""
    day: datetime = day_start(point)
    return day - timedelta(days=point.weekday())


def plus_week(point: datetime) -> datetime:
    """Get the point one week after the specified point."""
    return point + timedelta(days=7)


def format_delta_hm(delta: timedelta) -> str:
    """Format the delta as hours and minutes."""
    hours: int = int(delta.total_seconds() // 60 // 60)
    minutes: int = int(delta.total_seconds() // 60) - hours * 60
    return f"{hours:02d}:{minutes:02d}"


def format_delta(delta: timedelta) -> str:
    """Format the delta as a string."""
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
) -> bytearray | None:
    """Download the file from the address and save it to the cache path."""

    logging.info("Downloading `%s`...", address)

    timeout: Timeout = Timeout(connect=1.0, read=2.0)
    pool_manager: PoolManager = PoolManager(timeout=timeout)
    try:
        result: BaseHTTPResponse = pool_manager.request(
            "GET", address, preload_content=False
        )
    except urllib3.exceptions.MaxRetryError:
        return None
    pool_manager.clear()
    data: bytearray = bytearray()
    while True:
        try:
            buffer: bytes = result.read(buffer_size)
            if not buffer:
                break
            data.extend(buffer)
        except urllib3.exceptions.ReadTimeoutError:
            return None

    with cache_path.open("wb+") as temp_file:
        temp_file.write(data)

    return data


@dataclass
class MalformedFile(Exception):
    """File is malformed."""

    path: Path


@dataclass
class MalformedData(Exception):
    """Data is malformed."""

    message: str


def remove_parenthesis(text: str) -> str:
    """Remove the parenthesis from the text."""

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
    """Flatten the array using defined limits."""

    result: str = ""
    for i in array[:limit_1]:
        for j in i[:limit_2]:
            result += ("; " if result else "") + ", ".join(j[:limit_3])
    return result


def get_color(prompt: str) -> Color:
    """Get the randomish color for the prompt."""
    return Color("#" + str(hex(abs(hash(prompt))))[2:8])
