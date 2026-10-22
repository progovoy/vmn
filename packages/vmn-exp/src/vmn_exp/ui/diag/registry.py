#!/usr/bin/env python3
"""The dump's sections: ``register_section(name, fn)``; :func:`build_dump`
calls each, a raising one reported as ``{"error": repr}``.

A section must be cheap and must not wait on locks the request path holds
(read snapshots, try non-blocking acquires): the dump is taken when the
server is stuck. Every string of the dump is scrubbed of the secrets the
server registered (:func:`add_secret`) and of secret-looking env values.
"""
import os
import time
from datetime import datetime, timezone

FORMAT = 1
# Env vars whose values are scrubbed from a dump wherever they appear.
_SECRET_NAME_PARTS = ("SECRET", "TOKEN", "PASSWORD", "KEY", "CREDENTIAL")
# Shorter values would scrub ordinary words.
_MIN_SECRET_LEN = 6
REDACTED = "***"

_SECTIONS = {}  # name -> fn, in registration order
_SECRETS = set()


def rounded(value, digits=4):
    return None if value is None else round(value, digits)


def register_section(name, fn):
    """Add (or replace) the dump section *name*: ``fn()`` returns JSON data."""
    _SECTIONS[name] = fn


def add_secret(value):
    """Never let *value* (a token, a password) appear in a dump."""
    if value and len(value) >= _MIN_SECRET_LEN:
        _SECRETS.add(value)


def _env_secrets():
    return {
        value for name, value in os.environ.items()
        if any(part in name.upper() for part in _SECRET_NAME_PARTS)
        and len(value) >= _MIN_SECRET_LEN
    }


def _run(fn):
    started = time.monotonic()
    try:
        return fn()
    except Exception as exc:  # a broken section never breaks the dump
        return {"error": repr(exc), "elapsed_sec": round(time.monotonic() - started, 4)}


def build_dump():
    """``{"format", "taken_at", "pid", "sections"}``, scrubbed of secrets."""
    dump = {
        "format": FORMAT,
        "taken_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "pid": os.getpid(),
        "sections": {name: _run(fn) for name, fn in list(_SECTIONS.items())},
    }
    secrets = sorted(_SECRETS | _env_secrets(), key=len, reverse=True)
    return _scrub(dump, secrets) if secrets else dump


def _scrub(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret in value:
                value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {_scrub(k, secrets): _scrub(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, secrets) for v in value]
    return value
