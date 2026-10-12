#!/usr/bin/env python3
"""The owner id of a local record copy: the ``<owner>`` of its stream keys
(:mod:`vmn_exp.core.streams`).

Only a stream's owner ever appends to, ships, seals, compacts or pushes it.
A record directory keeps ``.stream-owner`` (JSON): one *view* entry — an
owner id, the directory's realpath and ``[st_dev, st_ino]`` as a process saw
it, the ids it retired — at the top level, the others under ``views``. A
process owns the entry of its view of the directory: the same ``(st_dev,
st_ino)`` (whatever path reached it: a symlink, a bind mount, a rename on one
filesystem — the recorded path is refreshed then), else the same inode at
the recorded path (a container seeing the directory with another st_dev). A
process matching no entry mints its own under the owner lock, re-reading the
file first, so every process of a view gets the same owner; its entry then
leads and the others stay under ``views``.

Every other id in the file is *inherited* (:func:`inherited`): another view's
(a container at another path), or a directory this one was copied, restored
or moved across filesystems from. Whether that original is gone cannot be
told from here, so inherited streams are never shipped, pushed nor compacted
automatically; :func:`adopt` (``vmn-exp push --adopt``) makes them this
view's, for when the user knows the original will never write again. A copy
deleted (``prune --local-only``, a cleared cache) and fetched again starts
without an owner. A stream once compacted is retired with its owner, so
nobody appends behind its ``.vmx``. Dot files are never listed nor pushed.
"""
import json
import os

from vmn_exp.core.streams import new_owner
from vmn_exp.storage import ship_state
from vmn_exp.storage.files import atomic_write

OWNER_FILE = ".stream-owner"


def _path(record_dir):
    return os.path.join(record_dir, OWNER_FILE)


def _where(record_dir):
    """``([st_dev, st_ino] or None, realpath)`` of directory *record_dir*."""
    try:
        st = os.stat(record_dir)
    except OSError:
        return None, os.path.realpath(record_dir)
    return [st.st_dev, st.st_ino], os.path.realpath(record_dir)


def _entries(record_dir):
    """The file's view entries, the leading one first ([] if absent)."""
    try:
        with open(_path(record_dir)) as f:
            found = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(found, dict):
        return []
    views = found.pop("views", None) or []
    return [e for e in [found, *views] if isinstance(e, dict) and isinstance(e.get("id"), str)]


def _write(record_dir, entries):
    lead, *others = entries
    atomic_write(_path(record_dir), json.dumps(dict(lead, views=others)))


def _ids(entry):
    return [entry["id"], *entry.get("retired", ())]


def _same_inode_here(entry, ident, real):
    seen = entry.get("ident")
    return isinstance(seen, list) and len(seen) == 2 and seen[1] == ident[1] \
        and entry.get("path") == real


def _mine(entries, where):
    """The index of the entry of the view *where*, None if there is none."""
    ident, real = where
    if ident is None:
        return None
    for i, e in enumerate(entries):
        if e.get("ident") == ident:
            return i
    for i, e in enumerate(entries):
        if _same_inode_here(e, ident, real):
            return i
    return None


def read_state(record_dir):
    """This view's entry ``{"id", "retired", ...}``, None before it has one."""
    entries = _entries(record_dir)
    i = _mine(entries, _where(record_dir))
    return None if i is None else entries[i]


def inherited(record_dir):
    """The owners of the other entries: their streams are never shipped,
    pushed nor compacted here until :func:`adopt`."""
    entries = _entries(record_dir)
    i = _mine(entries, _where(record_dir))
    return {o for j, e in enumerate(entries) if j != i for o in _ids(e)}


def _held_entries(record_dir):
    """Under the owner lock: the entries and the index of this view's,
    minted (or its path refreshed) and written if needed."""
    entries, where = _entries(record_dir), _where(record_dir)
    i = _mine(entries, where)
    if i is None:
        entries = [{"id": new_owner(), "path": where[1], "ident": where[0],
                    "retired": []}, *entries]
        _write(record_dir, entries)
        return entries, 0
    if entries[i].get("path") != where[1] and entries[i].get("ident") == where[0]:
        entries[i] = dict(entries[i], path=where[1])
        _write(record_dir, entries)
    return entries, i


def owner_state(record_dir):
    """This view's entry (created, or its path refreshed, if needed)."""
    found = read_state(record_dir)
    if found is not None and found.get("path") == _where(record_dir)[1]:
        return found
    with ship_state.owner_lock(record_dir):
        entries, i = _held_entries(record_dir)
        return entries[i]


def record_owner(record_dir):
    return owner_state(record_dir)["id"]


def retire_owner(record_dir, owner):
    """Retire *owner* if it is still this view's: the view's owner after."""
    with ship_state.owner_lock(record_dir):
        entries, i = _held_entries(record_dir)
        entry = entries[i]
        if entry["id"] != owner:
            return entry["id"]
        entries[i] = dict(entry, id=new_owner(), retired=[*entry.get("retired", ()), owner])
        _write(record_dir, entries)
        return entries[i]["id"]


def adopt(record_dir):
    """Make every inherited owner this view's (retired: shipped, never
    appended to); the other entries go. The owners adopted, sorted."""
    with ship_state.owner_lock(record_dir):
        entries, i = _held_entries(record_dir)
        theirs = sorted({o for j, e in enumerate(entries) if j != i for o in _ids(e)})
        if theirs:
            entry = entries[i]
            _write(record_dir, [dict(entry, retired=[*entry.get("retired", ()), *theirs])])
        return theirs
