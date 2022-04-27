"""
Emmio.

Utility for network connections using urllib3.
"""
import json
import time
from datetime import datetime, timedelta
from typing import Any

import urllib3

from emmio.ui import error, network

__author__ = "Sergey Vartanov"
__email__ = "me@enzet.ru"

DEFAULT_SLEEP_TIME: int = 2

last_request_time: datetime = datetime.now()


def get_data(
    address: str,
    parameters: dict[str, str],
    is_secure: bool = False,
    name: str = None,
    sleep_time: int = DEFAULT_SLEEP_TIME,
) -> bytes:
    """
    Construct Internet page URL and get data.

    :param address: first part of URL without "http://".
    :param parameters: URL parameters.
    :param is_secure: use `https://` instead of `http://`.
    :param name: short request name to display in logs.
    :param sleep_time: time to pause after request in seconds.
    :return: connection descriptor
    """
    global last_request_time

    url: str = f"http{('s' if is_secure else '')}://{address}"

    if not name:
        name = url

    # Sleep before the next request.
    diff: timedelta = datetime.now() - last_request_time
    last_request_time = datetime.now()
    if diff < timedelta(seconds=sleep_time):
        print(f"Sleeping for {sleep_time} seconds.")
        time.sleep(sleep_time)

    network(f"getting {name}")

    # Request content.
    pool_manager = urllib3.PoolManager()
    urllib3.disable_warnings()
    result = pool_manager.request("GET", url, parameters)
    pool_manager.clear()

    return result.data


def write_cache(data: bytes, kind: str, cache_file_name: str) -> Any:
    """
    Store requested data in cache file.

    :param data: requested data.
    :param kind: type of content: `html` or `json`.
    :param cache_file_name: name of cache file.
    """
    if kind == "json":
        try:
            object_ = json.loads(data.decode("utf-8"))
            if cache_file_name is not None:
                with open(cache_file_name, "w+") as cached:
                    cached.write(
                        json.dumps(object_, indent=4, ensure_ascii=False)
                    )
            return object_
        except ValueError:
            return None
    elif kind == "html":
        if cache_file_name is not None:
            with open(cache_file_name, "w+") as cached:
                cached.write(data.decode("utf-8"))
        return data.decode("utf-8")
    else:
        error(f"unknown data format {kind}")

    return None
