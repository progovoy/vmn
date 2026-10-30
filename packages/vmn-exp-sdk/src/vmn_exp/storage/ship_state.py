#!/usr/bin/env python3
"""What the remote holds of a record copy's streams, shared by the copy's
processes (a live run, a ``vmn-exp tag`` beside it).

A local stream file is the only source of its remote copy, so shipping is
resuming past the bytes the remote holds. A process remembering that in
memory would go stale once another process of the copy shipped and the
stream's segments were compacted under their names; so the state lives in
``<record>/.ship/<kind>.json`` (``{remote: {stream: [bytes, next seq]}}``),
read and written only under ``<record>/.ship/lock``, which every ship and
every compaction of the copy's own streams holds. A stream the state does not
know (a failed ship forgets it: its upload may have landed) is listed again.
"""
import collections
import functools
import json
import os
import threading
import time
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # not POSIX
    fcntl = None

from filelock import FileLock, Timeout
from vmn_exp.storage.files import atomic_write

SHIP_DIR = ".ship"
# A holder keeping the lock this long is stuck (a process frozen mid-upload):
# the ship gives up and the next one tries again. While the SDK's SIGTERM
# finalizer runs (:func:`finalizing`), the holder may be the main thread the
# signal froze mid-ship: the wait is short then.
LOCK_WAIT_SEC = 30
FINALIZING_WAIT_SEC = 2.0
_FINALIZING = threading.Event()

_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_DEPTH = threading.local()  # per thread: {lock path: [times held]}
# One fd open per lock file a process takes, so a hold (every heartbeat takes
# the state lock) is one flock, not a makedirs + open + close. At most
# _MAX_OPEN_FDS stay open (a server touches many records): the least recently
# used one nobody holds is closed for a new one.
_MAX_OPEN_FDS = 64
_FDS = collections.OrderedDict()  # lock path -> fd, least recently used first
_POLL_SEC = 0.05  # how often a contended lock file is tried again


def _thread_lock(path):
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(path, threading.RLock())


class ShipState:
    """One record copy's ship state of one *kind* (``log``/``metrics``) for
    the remote named *remote_id*."""

    def __init__(self, record_dir, kind, remote_id):
        self._dir = os.path.join(record_dir, SHIP_DIR)
        self._path = os.path.join(self._dir, f"{kind}.json")
        self._remote = remote_id
        self._streams = {}

    def get(self, stream):
        """``(bytes, next seq)`` the remote holds of *stream*, or None."""
        found = self._streams.get(stream)
        return tuple(found) if found else None

    def put(self, stream, state):
        self._streams[stream] = list(state)
        self._save()

    def forget(self, stream):
        if self._streams.pop(stream, None) is not None:
            self._save()

    def _load(self):
        try:
            with open(self._path) as f:
                found = json.load(f)
        except (OSError, ValueError):
            found = {}
        streams = found.get(self._remote) if isinstance(found, dict) else None
        self._streams = streams if isinstance(streams, dict) else {}
        self._all = found if isinstance(found, dict) else {}

    def _save(self):
        self._all[self._remote] = self._streams
        atomic_write(self._path, json.dumps(self._all))


def forget_streams(record_dir, which):
    """Under the ship lock: drop what every ship state of the copy remembers
    of the streams *which* accepts (a stream adopted from another owner)."""
    with ship_lock(record_dir):
        for kind in ("log", "metrics"):
            state = ShipState(record_dir, kind, None)
            state._load()
            kept = {remote: {s: v for s, v in streams.items() if not which(s)}
                    for remote, streams in state._all.items() if isinstance(streams, dict)}
            if kept != state._all:
                atomic_write(state._path, json.dumps(kept))


@contextmanager
def finalizing():
    """While the SDK's SIGTERM finalizer runs: ship locks are waited for at
    most :data:`FINALIZING_WAIT_SEC`."""
    _FINALIZING.set()
    try:
        yield
    finally:
        _FINALIZING.clear()


def is_finalizing():
    """Whether the SDK's SIGTERM finalizer is running (:func:`finalizing`)."""
    return _FINALIZING.is_set()


def live_rollup_due(seq, shipped_bytes, every, max_bytes, final_flush):
    """Whether a live stream rolls up what it shipped once segment *seq*
    (counted from its rollup's start) went, the remote then holding
    *shipped_bytes*: every *every*-th segment of a stream within *max_bytes*,
    on a periodic sync only — never in a finalizer or a final flush, which
    wait on the ship lock briefly."""
    return (0 < seq and seq % every == 0 and shipped_bytes <= max_bytes
            and not final_flush and not is_finalizing())


def _wait_sec():
    return FINALIZING_WAIT_SEC if _FINALIZING.is_set() else LOCK_WAIT_SEC


@contextmanager
def held(record_dir, kind, remote_id):
    """The copy's :class:`ShipState`, read under the copy's ship lock (held
    for the block, re-entrant in a thread)."""
    with ship_lock(record_dir):
        state = ShipState(record_dir, kind, remote_id)
        state._load()
        yield state


def ship_lock(record_dir):
    """The copy's ship lock: its processes and threads one at a time (a
    thread holding it may take it again)."""
    return _record_lock(record_dir, "lock")


def append_lock(record_dir):
    """The copy's metric append lock, held from choosing a block's stream to
    writing it, and by a compaction while it retires the stream it builds:
    a block lands before the build reads the file or in the next stream.
    Never held across remote calls."""
    return _record_lock(record_dir, "append.lock")


def owner_lock(record_dir):
    """The copy's owner lock, held while its ``.stream-owner`` is minted or
    changed: the innermost lock (nothing else is taken under it)."""
    return _record_lock(record_dir, "owner.lock")


def state_lock(record_dir):
    """The copy's state lock, held by a conditional state write from its
    compare to its rename (:meth:`LocalSnapshotStorage.save_file_if_match`);
    nothing else is taken under it."""
    return _record_lock(record_dir, "state.lock")


@contextmanager
def _record_lock(record_dir, name):
    """Lock *name* of the copy, given back in a ``finally`` the hold is taken
    in: an interrupt landing right after cannot leave it held."""
    path = os.path.join(record_dir, SHIP_DIR, name)
    local, depth = _thread_lock(path), _DEPTH.__dict__.setdefault(path, [0])
    held, release = [], None
    try:
        held.append(local.acquire(timeout=_wait_sec()))
        if not held[0]:
            raise RuntimeError(f"the record's {name} is held by a stuck thread")
        if not depth[0]:
            release = _lock_file(path, name)
        depth[0] += 1
        try:
            yield
        finally:
            depth[0] -= 1
    finally:
        if release is not None:
            release()
        if held and held[0]:
            local.release()


def _lock_file(path, name):
    """Take the cross-process lock of the file at *path* (its thread lock
    held); returns its release."""
    if fcntl is None:  # not POSIX: a lock file per hold
        file_lock = FileLock(path)
        try:
            file_lock.acquire(timeout=_wait_sec())
        except Timeout:
            raise _stuck_process(name) from None
        return file_lock.release
    deadline = time.monotonic() + _wait_sec()
    while True:
        fd = _open_fd(path)
        _flock(fd, deadline, name)
        if _is_current(fd, path):
            return functools.partial(_unlock_fd, path, fd)
        _unlock_fd(path, fd)  # the file was removed or replaced: lock the new one
        _close_fd(path)


def _flock(fd, deadline, name):
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise _stuck_process(name) from None
            time.sleep(_POLL_SEC)


def _stuck_process(name):
    return RuntimeError(f"the record's {name} is held by a stuck process")


def _open_fd(path):
    with _THREAD_LOCKS_GUARD:
        fd = _FDS.get(path)
        if fd is not None:
            _FDS.move_to_end(path)
            return fd
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    with _THREAD_LOCKS_GUARD:
        _evict_unheld()
        _FDS[path] = fd
    return fd


def _evict_unheld():
    """Close the least recently used fds no thread holds, down to the cap."""
    for path in list(_FDS)[: max(0, len(_FDS) + 1 - _MAX_OPEN_FDS)]:
        local = _THREAD_LOCKS[path]
        if local.acquire(blocking=False):
            try:
                if not _DEPTH.__dict__.get(path, [0])[0]:
                    os.close(_FDS.pop(path))
            finally:
                local.release()


def _is_current(fd, path):
    """Whether *fd* is still open on the file at *path*."""
    try:
        return os.path.samestat(os.fstat(fd), os.stat(path))
    except FileNotFoundError:
        return False


def _unlock_fd(path, fd):
    if _FDS.get(path) == fd:  # not closed since (a fork's child closes them all)
        fcntl.flock(fd, fcntl.LOCK_UN)


def _close_fd(path):
    with _THREAD_LOCKS_GUARD:
        os.close(_FDS.pop(path))


def _close_all_fds():
    """In a fork's child: the fds share the parent's open files, so a flock
    or unlock through them would be the parent's; the child opens its own."""
    while _FDS:
        os.close(_FDS.popitem()[1])


if fcntl is not None and hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_close_all_fds)
