#!/usr/bin/env python3
"""The owner id of a local record copy: the ``<owner>`` of its stream keys
(:mod:`vmn_exp.core.streams`).

A record directory keeps ``.stream-owner`` (JSON: the id, the directory's
absolute path, the ids it retired), created by the first process to need it;
the other processes over the copy read it, so they append to the same
streams. A file naming another path was copied along with its directory (a
``cp -r`` of the repo): the copy mints its own. A copy deleted (``prune
--local-only``, a cleared cache) and fetched again starts without one. A
stream once compacted is retired with its owner, so nobody appends behind
its ``.vmx``. Dot files are never listed nor pushed.
"""
import json
import os

from vmn_exp.core.streams import new_owner
from vmn_exp.storage.files import atomic_write

OWNER_FILE = ".stream-owner"


def _path(record_dir):
    return os.path.join(record_dir, OWNER_FILE)


def read_state(record_dir):
    """The copy's owner state, None before it has one."""
    try:
        with open(_path(record_dir)) as f:
            found = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or not isinstance(found.get("id"), str):
        return None
    if found.get("path") != os.path.abspath(record_dir):
        return None  # copied from elsewhere
    return found


def _state(record_dir, owner, retired=()):
    return {"id": owner, "path": os.path.abspath(record_dir), "retired": list(retired)}


def _create(record_dir):
    """Write a new owner unless another process got there first; the owner."""
    tmp = f"{_path(record_dir)}.{os.getpid()}.{new_owner()}"
    with open(tmp, "w") as f:
        json.dump(_state(record_dir, new_owner()), f)
    try:
        os.link(tmp, _path(record_dir))
    except FileExistsError:
        pass
    except OSError:
        os.replace(tmp, _path(record_dir))  # no hard links here
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    found = read_state(record_dir)
    if found is None:  # a copied file: replace it
        found = _state(record_dir, new_owner())
        atomic_write(_path(record_dir), json.dumps(found))
    return found


def owner_state(record_dir):
    """``{"id", "retired"}`` of the copy at *record_dir* (created if needed)."""
    return read_state(record_dir) or _create(record_dir)


def record_owner(record_dir):
    return owner_state(record_dir)["id"]


def retire_owner(record_dir, owner):
    """Retire *owner* if it is still the copy's: the copy's owner after."""
    found = owner_state(record_dir)
    if found["id"] != owner:
        return found["id"]
    state = _state(record_dir, new_owner(), found.get("retired", []) + [owner])
    atomic_write(_path(record_dir), json.dumps(state))
    return state["id"]
