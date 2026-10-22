#!/usr/bin/env python3
"""The highest ``.rN`` run this process claimed, per (store, app, code version).

Allocating a ``.rN`` name lists every run of the code version to find the
highest; a launcher registering many runs of one code version would list them
all again for each. With this hint the next run is claimed upward from the
last one instead (``create_exclusive`` keeps that race-free); see
:func:`vmn_exp.core.writer.allocate_run_verstr`.
"""
import threading

_HINTS = {}
_LOCK = threading.Lock()


def hint_key(storage, app_name, code_verstr):
    """The store (its ``cache_identity``, else the object) + app + code."""
    identity_of = getattr(storage, "cache_identity", None)
    identity = identity_of() if identity_of else None
    return (identity if identity is not None else id(storage), app_name, code_verstr)


def run_name(code_verstr, n):
    """The ``n``-th run's name: the bare code verstr, then ``.r2``, ``.r3``..."""
    return code_verstr if n == 1 else f"{code_verstr}.r{n}"


def run_number(code_verstr, verstr):
    """*verstr*'s ``N`` as a run of *code_verstr* (:func:`run_name`), else None."""
    if verstr == code_verstr:
        return 1
    rest = verstr[len(code_verstr) + 2:]
    if verstr.startswith(code_verstr + ".r") and rest.isdigit():
        return int(rest)
    return None


def get(key):
    with _LOCK:
        return _HINTS.get(key)


def note(key, n):
    """Remember run *n* as claimed (the hint only moves up)."""
    with _LOCK:
        _HINTS[key] = max(n, _HINTS.get(key, n))


def clear():
    with _LOCK:
        _HINTS.clear()
