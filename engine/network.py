"""
Utility for network connections.

Author: Sergey Vartanov (me@enzet.ru)
"""

import json
import os
import time

import urllib3

import util


def get_network_connection(address, parameters, is_secure=False, name=None):
    """
    Construct Internet page URL and get its descriptor.

    :param address: first part of URL without "http://"
    :param parameters: URL parameters
    :return: connection descriptor
    """
    url = 'http' + ('s' if is_secure else '') + '://' + address
    if len(parameters) > 0:
        url += '?' + parameters.keys()[0] + '=' + parameters.values()[0]
        for parameter in parameters.keys()[1:]:
            url += '&' + parameter + '=' + parameters[parameter]
    if not name:
        name = url
    util.network('getting ' + name)
    print("===========================================")
    http = urllib3.PoolManager()
    url = url.replace(' ', '_')
    try:
        result = http.request('GET', url)
    except UnicodeDecodeError:
        url = url.encode('utf-8')
        result = http.request('GET', url)
    except UnicodeEncodeError:
        url = str(url.encode('utf-8'))
        result = http.request('GET', url)
    time.sleep(2)
    return result


def get_file_name(address, parameters, cache_file_name, name=None,
        is_secure=False, exceptions=None):
    """
    Get file name.

    :param address: first part of URL without "http://" or "https://"
    :param parameters: URL parameters
    :param cache_file_name: name of cache file
    :param is_secure: use "https" instead of "http"
    :return: content if exist
    """
    if exceptions and address in exceptions:
        return None
    if os.path.isfile(cache_file_name):
        return cache_file_name
    else:
        #try:
            connection = get_network_connection(address, parameters,
                is_secure=is_secure, name=name)
            print('connected')
            cached = open(cache_file_name, 'wb+')
            print('opened')
            cached.write(connection.data)
            print('written')
            return cache_file_name
        #except Exception as e:
        #    util.error('during getting JSON from ' + address +
        #        ' with parameters ' + str(parameters))
        #    print(e)
        #    if exceptions:
        #        exceptions.append(address)
        #    return None


def get_content(address, parameters, cache_file_name, kind, name=None,
        is_secure=False, exceptions=None):
    """
    Read content from URL or from cached file.

    :param address: first part of URL without "http://" or "https://"
    :param parameters: URL parameters
    :param cache_file_name: name of cache file
    :param kind: type of content: "html" or "json"
    :param is_secure: use "https" instead of "http"
    :return: content if exist
    """
    if exceptions and address in exceptions:
        return None
    if cache_file_name and os.path.isfile(cache_file_name):
        cache_file = open(cache_file_name)
        if kind == 'json':
            try:
                return json.load(cache_file)
            except ValueError:
                return None
        if kind == 'html':
            return cache_file.read()
    else:
        try:
            connection = get_network_connection(address, parameters,
                is_secure=is_secure, name=name)
            if kind == 'json':
                try:
                    obj = json.load(connection)
                    if cache_file_name:
                        cached = open(cache_file_name, 'w+')
                        cached.write(json.dumps(obj))
                    return obj
                except ValueError:
                    util.error('cannot get ' + address + ' ' + str(parameters))
                    return None
            if kind == 'html':
                content = connection.read()
                if cache_file_name:
                    cached = open(cache_file_name, 'w+')
                    cached.write(content)
                return content
        except Exception as e:
            util.error('during getting JSON from ' + address +
                ' with parameters ' + str(parameters))
            print(e)
            if exceptions:
                exceptions.append(address)
            return None
