#!/usr/bin/env python3
"""Upgrading a file of older records
(:data:`~vmn_exp.core.index_store_schema.RECORDS_VERSION`), one upgrader at a
time: :func:`upgrade` holds the ``<path>.upgrade`` file lock (threads take
turns under it too) and re-reads the pointer once it holds it, so one that
waited opens what the one before it built (plan 33 §2.1).

Records whose version is in
:data:`~vmn_exp.core.index_store_schema.COPYABLE_RECORDS` still read right:
the file is upgraded in place (plan 33 §2.3), which drops nothing and needs
no extra disk. A version with a stale predicate gets a read pass that takes
no lock: it picks the records that predicate says do not read right; they
are listed to read again (:mod:`vmn_exp.core.index_reread`) in one
transaction, then deleted with their run states, rows and similar-runs
documents, :data:`DELETE_CHUNK` per short write transaction. The kept records
its version's :data:`~vmn_exp.core.index_store_schema.CHECKED_RECORDS`
predicate picks are listed, in the same transaction, for a background check
(:mod:`vmn_exp.core.index_vmx_check`). A version with none reads no record
here (at ~734k runs on S3 the pass held the board empty for minutes, plan 34
§4): the check lists its own, a chunk per step. Last, one transaction picks
(lists and deletes) the records saved since any read pass, marks every app to re-derive
(:mod:`vmn_exp.core.index_derive`) and writes the records mark; the journal
mark and listing baselines stay. Until that mark the file still reads as
outdated, so an upgrade that died part way is finished by the next open. The
kept rows are served, ``loading``, while the derive rewrites them.

Other records cannot be trusted: :func:`regenerate` builds a new, empty
generation file beside the old one (:mod:`vmn_exp.core.sqlite_files`), which
loads afresh from storage, and flips the pointer to it; the old file is not
written to, and goes once nothing holds it open (the sweep). It first checks
the disk has room for a file as big as the old one, refusing (an OSError
naming the bytes and the path) when not (plan 33 §2.4).
"""
import json
import os
import shutil

from filelock import FileLock, Timeout

from vmn_exp.core import index_reread, index_store_schema, index_vmx_check, sqlite_files
from vmn_exp.core.index_lean_store import write_lean
from vmn_exp.core.index_store_kv import write_puts
from vmn_exp.core.index_store_schema import RecordsOutdated, upgrade_derived
from vmn_exp.core.similar_filing import file_records
from vmn_exp.core.sqlite_conn import connect, in_chunks, write_tx

SCAN_CHUNK = 500  # records the read pass reads per query
DELETE_CHUNK = 500  # picked records deleted per transaction
LOCK_SUFFIX = ".upgrade"


def upgrade(path, connect_file):
    """``(connection, file)`` of *path*'s live database opened through
    *connect_file(file)*, upgraded first when its records are outdated (see
    the module)."""
    with FileLock(path + LOCK_SUFFIX):  # one per open: threads take turns too
        file = sqlite_files.live_path(path)
        try:
            return connect_file(file), file
        except RecordsOutdated as exc:
            found = exc.found
        if found not in index_store_schema.COPYABLE_RECORDS:
            return regenerate(path, file, connect_file)
        upgrade_in_place(file, found)
        return connect_file(file), file


def upgrading(path):
    """Whether an upgrader holds *path*'s upgrade lock now (never waits)."""
    lock = FileLock(path + LOCK_SUFFIX, timeout=0)
    try:
        lock.acquire()
    except Timeout:
        return True
    lock.release()
    return False


def upgrade_in_place(file, found):
    """Bring *file*'s records (version *found*) to this version in place,
    deleting those its stale predicate picks and listing those its check
    predicate picks for the background check (see the module). With no
    stale predicate nothing is read here: the check lists its own, a chunk
    per step (:func:`~vmn_exp.core.index_vmx_check.list_later`)."""
    stale = index_store_schema.COPYABLE_RECORDS[found]
    check = index_store_schema.CHECKED_RECORDS.get(found)
    conn = connect(file)
    try:
        if stale is not None:
            gens = dict(conn.execute("SELECT app, gen FROM exp_index_gen"))
            picked, checked = _split(_rows(file), stale, check)
            with write_tx(conn):  # listed first: a death part way loses none
                _list(conn, picked, checked)
            for chunk, _ in in_chunks(picked, DELETE_CHUNK):
                _delete_picked(conn, chunk)
        with write_tx(conn):
            if stale is not None:
                late, late_checked = _split(_saved_since(conn, gens), stale, check)
                _list(conn, late, late_checked)
                _delete(conn, late)
            elif check is not None:
                write_puts(conn, index_vmx_check.list_later(conn, found))
            upgrade_derived(conn, kept=True)
    finally:
        conn.close()


def _rows(file):
    """``((app, key), head, data)`` of *file*'s records, read a chunk per
    query on a read-only connection: no lock is held across the pass."""
    source = connect(file, readonly=True)
    after = 0
    try:
        while True:
            rows = source.execute(
                "SELECT rowid, app, key, head, data FROM exp_index WHERE rowid > ?"
                " ORDER BY rowid LIMIT ?", (after, SCAN_CHUNK)).fetchall()
            if not rows:
                return
            yield from (((app, key), head, data) for _, app, key, head, data in rows)
            after = rows[-1][0]
    finally:
        source.close()


def _saved_since(conn, gens):
    """``((app, key), head, data)`` of the records saved past *gens* (``{app: gen}``)."""
    apps = [app for (app,) in conn.execute("SELECT app FROM exp_index_gen").fetchall()]
    return [((app, key), head, data) for app in apps
            for key, head, data in conn.execute(
                "SELECT key, head, data FROM exp_index WHERE app = ? AND seq > ?",
                (app, gens.get(app, 0)))]


def _split(rows, stale, check):
    """``(picked, checked)``: the items of *rows* *stale* picks, and of the
    others those *check* picks."""
    picked, checked = [], []
    for item, head, data in rows:
        if data is None:
            continue
        fold = json.loads(data)
        if stale is not None and stale(fold):
            picked.append(item)
        elif check is not None and check(json.loads(head), fold):
            checked.append(item)
    return picked, checked


def _list(conn, picked, checked):
    write_puts(conn, index_reread.puts(conn, picked) + index_vmx_check.puts(conn, checked))


def _delete_picked(conn, picked):
    """Delete *picked*, in one transaction."""
    with write_tx(conn):
        _delete(conn, picked)


def _delete(conn, picked):
    """Delete *picked* (``(app, key)``) records with all that is derived from
    them."""
    by_app = {}
    for app, key in picked:
        by_app.setdefault(app, []).append(key)
    for app, keys in by_app.items():
        pairs = [(app, key) for key in keys]
        conn.executemany("DELETE FROM exp_index WHERE app = ? AND key = ?", pairs)
        conn.executemany("DELETE FROM exp_index_state WHERE app = ? AND key = ?", pairs)
        write_lean(conn, app, None, {}, keys, {}, {}, renumber=False)
        file_records(conn, app, {}, keys)


def regenerate(path, old, connect_file):
    """``(connection, file)`` of a new, empty generation of *path*'s
    database, live, built beside its *old* file through *connect_file(file)*;
    OSError when the disk has no room for it."""
    _check_room(path, old)
    fresh = sqlite_files.new_generation(path)
    conn = None
    try:
        conn = connect_file(fresh)
        sqlite_files.flip(path, fresh)
    except BaseException:
        if conn is not None:
            conn.close()
        sqlite_files.remove_if_unused(fresh)
        raise
    return conn, fresh


def _check_room(path, old):
    """Refuse a new generation the disk has no room for: it grows as big as
    *old* (with its WAL) while *old* stays until swept."""
    needed = sum(os.path.getsize(f) for f in (old, old + "-wal") if os.path.exists(f))
    folder = os.path.dirname(os.path.abspath(path))
    free = shutil.disk_usage(folder).free
    if free < needed:
        raise OSError(f"no room for a new generation of {path}: it needs {needed} bytes,"
                      f" {free} free in {folder}")
