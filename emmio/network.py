"""
Utility for network connections using urllib3.

Author: Sergey Vartanov (me@enzet.ru)
"""

import json
import os
import urllib3
import time

from datetime import datetime, timedelta
from typing import Dict, List

from emmio import util

DEFAULT_SLEEP_TIME = 2


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
    url = f"http{('s' if is_secure else '')}://{address}"

    if not name:
        name = url

    util.network(f"getting {name}")

    # Request content.
    pool_manager = urllib3.PoolManager()
    urllib3.disable_warnings()
    result = pool_manager.request("GET", url, parameters)
    pool_manager.clear()

    # Just to be sure you're not making too many requests.
    if sleep_time:
        time.sleep(sleep_time)

    return result.data


def get_content(address: str, parameters: Dict[str, str], cache_file_name: str,
        kind: str, is_secure: bool, name: str = None, exceptions=None,
        update_cache: bool = False):
    """
    Read content from URL or from cached file.

    :param address: first part of URL without "http://"
    :param parameters: URL parameters
    :param cache_file_name: name of cache file
    :param kind: type of content: `html` or `json`
    :param is_secure: use `https://` instead of `http://`.
    :return: content if exist.
    """
    if exceptions and address in exceptions:
        return None

    if cache_file_name is not None:
        os.makedirs(os.path.dirname(cache_file_name), exist_ok=True)

    if cache_file_name is not None and os.path.isfile(cache_file_name) and \
            datetime(1, 1, 1).fromtimestamp(os.stat(cache_file_name).st_mtime) > \
                datetime.now() - timedelta(days=90) and \
            not update_cache:
        with open(cache_file_name) as cache_file:
            if kind == "json":
                try:
                    return json.load(cache_file)
                except ValueError:
                    return None
            if kind == "html":
                return cache_file.read()
    else:
        try:
            data = get_data(address, parameters, is_secure=is_secure, name=name)
            if kind == "json":
                try:
                    obj = json.loads(data.decode("utf-8"))
                    if cache_file_name is not None:
                        with open(cache_file_name, "w+") as cached:
                            cached.write(json.dumps(obj, indent=4))
                    return obj
                except ValueError:
                    util.error("cannot get " + address + " " + str(parameters))
                    return None
            elif kind == "html":
                if cache_file_name is not None:
                    with open(cache_file_name, "w+") as cached:
                        cached.write(data)
                return data.decode("utf-8")
            else:
                print("Error: unknown format.")
        except Exception as e:
            util.error("during getting JSON from " + address + " with parameters " + str(parameters))
            print(e)
            if exceptions:
                exceptions.append(address)
            return None
