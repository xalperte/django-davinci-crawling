# -*- coding: utf-8 -*-
# Copyright (c) 2018-2019 PreSeries Tech, SL

import json
import requests
import logging
import cgi
import os
import tempfile

from time import sleep
from requests.exceptions import RequestException
from bs4 import BeautifulSoup

from .exceptions import DownloadException
from .io import copy_file

logger = logging.getLogger("davinci_crawling")

APPLICATION_FORM = {"Content-Type": "application/x-www-form-urlencoded"}
APPLICATION_JSON = {"Content-Type": "application/json"}
USER_AGENT = {'User-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_4)'
                            ' AppleWebKit/537.36 (KHML, like Gecko)'
                            ' Chrome/51.0.2704.103 Safari/537.36'}

DEFAULT_TIMEOUT = 60

# HTTP Status Codes
HTTP_OK = 200
HTTP_CREATED = 201
HTTP_ACCEPTED = 202
HTTP_NO_CONTENT = 204
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_PAYMENT_REQUIRED = 402
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_LENGTH_REQUIRED = 411
HTTP_INTERNAL_SERVER_ERROR = 500

HTTP_INTERNAL_ERROR = 999


class Page(object):

    def __init__(self, status, body, response=None):
        self.status = status
        self.body = body
        self.response = response


class File(object):

    def __init__(self, status, file, filename, response=None):

        self.status = status
        self.file = file
        self.filename = filename
        self.response = response


def post_json(url, json_obj, timeout=None):
    """
    Send and receive json by posting to the given URL.
    The body should be provided as a map for conversion
    to json
    """
    try:
        json_body = json.dumps(json_obj)

        timeout = timeout if timeout else DEFAULT_TIMEOUT

        return requests.post(
            url=url, data=json_body,
            headers={**APPLICATION_JSON, **USER_AGENT},
            timeout=(timeout, timeout), verify=False)
    except RequestException as ex:
        logger.exception("Unable to send the POST. Cause: %s" % ex)
        raise ex


def post_form(url, json_obj, timeout=None):
    """
    Send and receive json by posting to the given URL.
    The body should be provided as a map for conversion
    to json
    """
    try:
        timeout = timeout if timeout else DEFAULT_TIMEOUT

        return requests.post(
            url=url, data=json_obj,
            headers={**APPLICATION_FORM, **USER_AGENT},
            timeout=(timeout, timeout), verify=False)
    except RequestException as ex:
        logger.exception("Unable to send the POST. Cause: %s" % ex)
        raise ex


def fetch_page(url, timeout):
    """
    Get a raw page fro the url
    """
    logger.info("Fetching page for %s" % url)
    return requests.get(url, headers=USER_AGENT,
                        timeout=(timeout, timeout), verify=False)


def parse_json(s):
    """
    Parse the given json string into a python dictionary
    """
    return json.loads(s) if s else None


def fetch_json(url, timeout=None):
    """
    Get a json resul from a url
    """
    response = fetch_page(url, timeout if timeout else DEFAULT_TIMEOUT)
    if response.status_code < HTTP_BAD_REQUEST:
        return Page(response.status_code, response.json, response)
    return Page(response.status_code, response.text, response)


def fetch_html(url, timeout=None):
    """
    Get a json resul from a url
    """
    response = fetch_page(url, timeout if timeout else DEFAULT_TIMEOUT)
    if response.status_code < HTTP_BAD_REQUEST:
        return Page(
            response.status_code, BeautifulSoup(response.text), response)
    return Page(response.status_code, response.text, response)


def __constatly_true(status):
    return True


def fetch_tenaciously(fetcher, url, n, s,
                      data=None, error_callback=__constatly_true):
    n -= 1
    try:
        page = fetcher(url) if not data else fetcher(url, data)
        status_code = page.response.status_code
        if status_code < HTTP_BAD_REQUEST:
            return page
        else:
            logger.warning("%d status returned for %s. "
                           "Max %d attempts remaining." %
                           (status_code, url, n))
            # logger.warning("Headers: %s" % page.response.headers)
            return __maybe_retry(
                fetcher, url, n, s, data, page, error_callback)
    except Exception as ex:
        logger.exception("Exception thrown for %s:%s."
                         " Max %d attempts remaining" %
                         (url, ex, n))
        return __maybe_retry(fetcher, url, n, s, data,
                             Page(HTTP_INTERNAL_ERROR, str(ex)),
                             error_callback)


def __maybe_retry(fetcher, url, n, s, data, page, error_callback=None):
    if error_callback and error_callback(page) and (n > 0):
        logger.info("Sleeping for %s seconds before next retry." % s)
        sleep(s)
        return fetch_tenaciously(fetcher, url, n, s,
                                 data=data, error_callback=error_callback)
    else:
        logger.info("No more tries (exhausted or "
                    "short-circuited by error callback")
        return page


def __content_error(status):
    raise Exception("Download failed with http status [%d]" % status)


def fetch_file(url, options):
    with tempfile.TemporaryDirectory() as temp_path:
        logger.info(
            "Download from [%s] and store into [%s]" % (url, temp_path))
        try:
            response = requests.get(
                url, stream=True, timeout=(1800, 1800), verify=False)

            params = cgi.parse_header(
                response.headers.get('Content-Disposition', ''))[-1]
            if 'filename' not in params:
                raise ValueError('Could not find a filename')

            filename = os.path.basename(params['filename'])
            abs_path = os.path.join(temp_path, filename)

            status = response.status_code
            response = response if status == HTTP_OK \
                else __content_error(status)

            with open(abs_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

            base_path = options.get("base_path", ".")

            dest_file = "{0}/{1}".format(base_path, filename)
            dest_file = copy_file(options, abs_path, dest_file)

            return File(status, dest_file, filename, response)
        except Exception as ex:
            logger.exception("Failed to download %s" % url)
            raise DownloadException(url) from ex
