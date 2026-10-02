#!/usr/bin/env python3
"""The two HTTP calls OIDC needs, over stdlib urllib (tests inject a fake)."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

TIMEOUT_SEC = 10


class UrllibHttp:
    def get_json(self, url):
        with urllib.request.urlopen(url, timeout=TIMEOUT_SEC) as resp:
            return json.load(resp)

    def post_form(self, url, data):
        req = urllib.request.Request(
            url,
            data=urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            return _error_body(exc)


def _error_body(exc):
    """An OAuth error response (``{"error": ...}``, RFC 6749 5.2), else re-raise."""
    try:
        body = json.load(exc)
    except ValueError:
        raise exc
    if not isinstance(body, dict) or "error" not in body:
        raise exc
    return body
