#!/usr/bin/env python3
"""The two HTTP calls OIDC needs, over stdlib urllib (tests inject a fake).

A redirected answer is refused: discovery and the token endpoint must answer
at the https URL that was checked, never at one a redirect points to.
"""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

TIMEOUT_SEC = 10


class RedirectRefused(urllib.error.URLError):
    pass


class UrllibHttp:
    def get_json(self, url):
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            return json.load(_not_redirected(resp, url))

    def post_form(self, url, data):
        req = urllib.request.Request(
            url,
            data=urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.load(_not_redirected(resp, url))
        except urllib.error.HTTPError as exc:
            return _error_body(_not_redirected(exc, url))


def _not_redirected(resp, url):
    """*resp* when it answers *url* itself, else :class:`RedirectRefused`."""
    if resp.geturl() != url:
        raise RedirectRefused(f"redirect from {url} to {resp.geturl()} refused")
    return resp


def _error_body(exc):
    """An OAuth error response (``{"error": ...}``, RFC 6749 5.2), else re-raise."""
    try:
        body = json.load(exc)
    except ValueError:
        raise exc
    if not isinstance(body, dict) or "error" not in body:
        raise exc
    return body
