#!/usr/bin/env python3
"""The owner id of a local record copy: the ``<owner>`` of its stream keys
(:mod:`vmn_exp.core.streams`).

A record directory keeps ``.stream-owner`` (JSON: the id, the directory's
absolute path, the ids it retired, the ids it inherited), created by the
first process to need it; the other processes over the copy read it, so they
append to the same streams. A file naming another path came with its
directory — a ``cp -r`` of the repo, a moved checkout, a push rename: the
copy never appends to the recorded owner (the original may have gone on
appending and shipping), it mints its own and inherits the old one's streams
with the path of the record they came from (:func:`inherited`). Their local
files never grow again; once that record is gone (moved, deleted) the copy
ships what the remote lacks of them — not before, while the original alone
ships them and trusts its ship state. Minting happens under the copy's owner
lock, re-reading the file first, so every process of the copy gets the same
new owner. A copy deleted (``prune --local-only``, a
cleared cache) and fetched again starts without one. A stream once compacted
is retired with its owner, so nobody appends behind its ``.vmx``. Dot files
are never listed nor pushed.
"""
import json
import os

from vmn_exp.core.streams import new_owner
from vmn_exp.storage import ship_state
from vmn_exp.storage.files import atomic_write

OWNER_FILE = ".stream-owner"


def _path(record_dir):
    return os.path.join(record_dir, OWNER_FILE)


def _read(record_dir):
    """The owner file as written (maybe another path's), None if absent."""
    try:
        with open(_path(record_dir)) as f:
            found = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or not isinstance(found.get("id"), str):
        return None
    return found


def _is_here(found, record_dir):
    return found is not None and found.get("path") == os.path.abspath(record_dir)


def _all_owners(found):
    """``{owner: path of its record}`` of *found* and all it retired or inherited."""
    path = found.get("path")
    owners = {o: path for o in (found["id"], *found.get("retired", ()))}
    owners.update(found.get("inherited") or {})
    return owners


def read_state(record_dir):
    """The copy's owner state, None before it has one of its own."""
    found = _read(record_dir)
    return found if _is_here(found, record_dir) else None


def inherited(record_dir):
    """The owners whose streams came with the copy's directory from a record
    that is gone: shipped and pushed past what the remote holds, never
    appended to nor compacted here."""
    found = _read(record_dir)
    if found is None:
        return set()
    if _is_here(found, record_dir):
        owners = found.get("inherited") or {}
    else:
        owners = _all_owners(found)
    return {o for o, path in owners.items() if not os.path.isdir(str(path))}


def _state(record_dir, owner, retired=(), inherits=None):
    return {"id": owner, "path": os.path.abspath(record_dir),
            "retired": list(retired), "inherited": dict(inherits or {})}


def _mint(record_dir):
    """Under the owner lock: the copy's state, minted unless another process
    did first."""
    found = _read(record_dir)
    if _is_here(found, record_dir):
        return found
    state = _state(record_dir, new_owner(), inherits=_all_owners(found) if found else None)
    atomic_write(_path(record_dir), json.dumps(state))
    return state


def owner_state(record_dir):
    """``{"id", "retired", "inherited"}`` of the copy at *record_dir*
    (created if needed)."""
    found = read_state(record_dir)
    if found is not None:
        return found
    with ship_state.owner_lock(record_dir):
        return _mint(record_dir)


def record_owner(record_dir):
    return owner_state(record_dir)["id"]


def retire_owner(record_dir, owner):
    """Retire *owner* if it is still the copy's: the copy's owner after."""
    with ship_state.owner_lock(record_dir):
        found = _mint(record_dir)
        if found["id"] != owner:
            return found["id"]
        state = _state(record_dir, new_owner(), found.get("retired", []) + [owner],
                       found.get("inherited"))
        atomic_write(_path(record_dir), json.dumps(state))
        return state["id"]
