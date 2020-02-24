"""
Emmio.

Utility for network connections using urllib3.

Author: Sergey Vartanov (me@enzet.ru).
"""
import json
import os
import time
import urllib3

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from emmio import util

DEFAULT_SLEEP_TIME: int = 2

last_request_time: datetime = datetime.now()


def get_data(address: str, parameters: Dict[str, str], is_secure: bool = False,
        name: str = None, sleep_time: int = DEFAULT_SLEEP_TIME) -> bytes:
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
    diff: timedelta = (datetime.now() - last_request_time)
    last_request_time = datetime.now()
    if diff < timedelta(seconds=sleep_time):
        print(f"Sleeping for {sleep_time} seconds.")
        time.sleep(sleep_time)

    util.network(f"getting {name}")

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
                    cached.write(json.dumps(
                        object_, indent=4, ensure_ascii=False))
            return object_
        except ValueError:
            return None
    elif kind == "html":
        if cache_file_name is not None:
            with open(cache_file_name, "w+") as cached:
                cached.write(data.decode("utf-8"))
        return data.decode("utf-8")
    else:
        util.error(f"unknown data format {kind}")

    return None


def get_content(address: str, parameters: Dict[str, str],
        cache_file_name: Optional[str], kind: str, is_secure: bool,
        name: str = None, update_cache: bool = False) -> Any:
    """
    Read content from URL or from cached file.

    :param address: first part of URL without "http://"
    :param parameters: URL parameters
    :param cache_file_name: name of cache file
    :param kind: type of content: `html` or `json`
    :param is_secure: use `https://` instead of `http://`.
    :param name: short request name to display in logs.
    :param update_cache: rewrite cache file.
    :return: content if exist.
    """
    if cache_file_name is not None:
        os.makedirs(os.path.dirname(cache_file_name), exist_ok=True)

    # Read from the cache file.

    if cache_file_name is not None and not update_cache and \
            os.path.isfile(cache_file_name):
        with open(cache_file_name) as cache_file:
            if kind == "json":
                try:
                    return json.load(cache_file)
                except ValueError:
                    return None
            elif kind == "html":
                return cache_file.read()
            else:
                util.error(f"unknown data format {kind}")

    # Read from the network.

    try:
        data: bytes = \
            get_data(address, parameters, is_secure=is_secure, name=name)
        if cache_file_name is not None:
            return write_cache(data, kind, cache_file_name)
    except Exception as e:
        print(e)
        return None

    return None
