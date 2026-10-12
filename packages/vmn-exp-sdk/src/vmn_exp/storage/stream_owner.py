#!/usr/bin/env python3
"""The owner id of a local record copy: the ``<owner>`` of its stream keys
(:mod:`vmn_exp.core.streams`).

A record directory keeps ``.stream-owner`` (JSON: the id, the directory's
realpath and ``[st_dev, st_ino]``, the ids it retired, the ids it inherited
with the record each came from), created by the first process to need it;
the other processes over the copy read it, so they append to the same
streams. A copy is the physical directory, whatever path reached it (a
symlink, a bind mount, a move on one filesystem): the same ``(st_dev,
st_ino)`` is the same copy. Another directory — a ``cp -r`` of the repo, a
backup restored at the original's path, a cross-filesystem move — never
appends to the recorded owner (the original may have gone on appending and
shipping): it mints its own and inherits the old one's streams with the
record they came from (:func:`inherited`). Their local files never grow
again; the copy ships what the remote lacks of them unless their record is
another directory that is still there, which alone ships them and trusts its
ship state. A process seeing this very directory with another identity (a
container's st_dev) mints too, and ships the streams whose record is the
directory as it sees it: no stream is left without a shipper. A file from
before identities counts as another directory. Minting happens under the
copy's owner lock, re-reading the file first, so every process of the copy
gets the same new owner. A copy deleted (``prune --local-only``, a cleared
cache) and fetched again starts without one. A stream once compacted is
retired with its owner, so nobody appends behind its ``.vmx``. Dot files are
never listed nor pushed.
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


def _identity(path):
    """``[st_dev, st_ino]`` of directory *path*, None if it is not there."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_dev, st.st_ino]


def _is_here(found, record_dir):
    ident = found.get("ident") if found else None
    return ident is not None and ident == _identity(record_dir)


def _origin(found):
    return {"path": found.get("path"), "ident": found.get("ident")}


def _all_owners(found):
    """``{owner: its record}`` of *found* and all it retired or inherited."""
    owners = {o: _origin(found) for o in (found["id"], *found.get("retired", ()))}
    owners.update(found.get("inherited") or {})
    return owners


def _shipped_elsewhere(origin, mine):
    """Whether *origin* is another directory, still there (it ships its own)."""
    if not isinstance(origin, dict) or origin.get("ident") in (None, mine):
        return False
    return _identity(str(origin.get("path"))) == origin["ident"]


def read_state(record_dir):
    """The copy's owner state, None before it has one of its own."""
    found = _read(record_dir)
    return found if _is_here(found, record_dir) else None


def inherited(record_dir):
    """The owners whose streams came with the copy's directory from a record
    that is not another live directory (gone, or this one as another
    process saw it): shipped and pushed past what the remote holds, never
    appended to nor compacted here."""
    found = _read(record_dir)
    if found is None:
        return set()
    if _is_here(found, record_dir):
        owners = found.get("inherited") or {}
    else:
        owners = _all_owners(found)
    mine = _identity(record_dir)
    return {o for o, origin in owners.items() if not _shipped_elsewhere(origin, mine)}


def _state(record_dir, owner, retired=(), inherits=None):
    return {"id": owner, "path": os.path.realpath(record_dir),
            "ident": _identity(record_dir), "retired": list(retired),
            "inherited": dict(inherits or {})}


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
