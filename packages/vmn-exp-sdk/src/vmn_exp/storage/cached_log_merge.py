#!/usr/bin/env python3
"""Keeping the local copy of a writer's log a superset of the remote's
(the log half of local-first storage, :mod:`cached_logs`).

Shipping resumes past the bytes the remote holds, which only works while the
remote copy is a prefix of the local one. A local copy can lag the remote one
under the same writer id: a fresh clone, a cleared cache, another clone on the
same host. Before its first append under a writer, a cache brings its local
copy up to the remote's (:meth:`LogMerge._seed_local_log`). Where that cannot
be relied on — the seed failed, here or in an earlier process over the same
root, or the local copy was dropped under a live cache — shipping merges the
remote's lines back in first (:meth:`LogMerge._needs_merge`) rather than
overwrite them or ship from an offset the local copy does not line up with.

Neither the seed nor the local append waits on the sync lock a ship holds
across remote I/O. Appends share the local log lock, a merge's rewrite holds
it alone (:class:`LocalLogLock`): an append waits for a rewrite, which would
drop a line appended meanwhile, but only briefly while the SDK's SIGTERM
finalizer runs (:func:`finalizing`) — it appends from a worker thread while
the main thread sits wherever the signal caught it, maybe mid-rewrite.
"""

import threading
import time
from collections import Counter
from contextlib import contextmanager

from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.files import log_object_name, log_writer_and_seq
from vmn_exp.storage.s3_base import parallel_map

# The local log lock is held for local file I/O only, so a holder keeping it
# this long was interrupted where it stood (the SDK's SIGTERM finalizer runs
# while the main thread sits wherever the signal caught it): a rewrite then
# gives up, and so does an append while finalizing.
LOCAL_LOCK_WAIT_SEC = 2.0
_FINALIZING = threading.Event()


@contextmanager
def finalizing():
    """While the SDK's SIGTERM finalizer runs: every local append waits at
    most :data:`LOCAL_LOCK_WAIT_SEC` for a rewrite, then goes on without the
    lock (the rewrite may be the interrupted main thread's)."""
    _FINALIZING.set()
    try:
        yield
    finally:
        _FINALIZING.clear()


class LocalLogLock:
    """Shared by local appends — each is one write of whole lines, so they
    never need to exclude each other — and held alone by a rewrite (read,
    merge, replace), which must not run while an append lands."""

    def __init__(self):
        self._mutex = threading.Lock()
        self._changed = threading.Condition(self._mutex)
        self._appends = 0
        self._rewriting = False

    def acquire_append(self, wait=None):
        """Wait for no rewrite to run — at most *wait* seconds (None: for as
        long as it takes); False when that ran out."""
        return self._enter(lambda: not self._rewriting, self._count_append, wait)

    def release_append(self):
        self._leave(self._uncount_append)

    def acquire_rewrite(self, wait):
        """Wait at most *wait* seconds to be alone; False when that ran out."""
        return self._enter(lambda: not self._rewriting and not self._appends,
                           self._start_rewrite, wait)

    def release_rewrite(self):
        self._leave(self._end_rewrite)

    def _enter(self, free, claim, wait):
        # The mutex too is waited for at most *wait*: a thread a signal froze
        # may hold it.
        start = time.monotonic()
        if not self._mutex.acquire(timeout=-1 if wait is None else wait):
            return False
        try:
            left = None if wait is None else max(0.0, wait - (time.monotonic() - start))
            if not self._changed.wait_for(free, left):
                return False
            claim()
            return True
        finally:
            self._mutex.release()

    def _leave(self, unclaim):
        with self._mutex:
            unclaim()
            self._changed.notify_all()

    def _count_append(self):
        self._appends += 1

    def _uncount_append(self):
        self._appends -= 1

    def _start_rewrite(self):
        self._rewriting = True

    def _end_rewrite(self):
        self._rewriting = False


def _lines(data):
    """The complete lines of *data*, each with its newline."""
    return [line + b"\n" for line in data.split(b"\n")[:-1]]


def _with_missing_lines(remote, local):
    """*remote* followed by the lines of *local* it lacks — counted, so a
    line logged twice stays twice."""
    have = Counter(_lines(remote))
    missing = []
    for line in _lines(local):
        if have[line]:
            have[line] -= 1
        else:
            missing.append(line)
    return remote + b"".join(missing)


def next_seq(objects):
    """The segment after the writer's remote log *objects*."""
    seqs = [log_writer_and_seq(name)[1] for name, _ in objects]
    return max(seqs) + 1 if seqs else 0


class LogMerge:
    """Mixed into :class:`~vmn_exp.storage.cached_logs.CachedLogs`, whose
    ``_local`` and ``_remote`` it uses."""

    def _init_log_merge(self):
        self._seeded = set()  # (app, verstr, writer) whose local log met the remote's
        self._seed_failed = set()  # ... whose seed raised: the next ship merges
        # Held by local appends and the local half of a merge, never across
        # remote I/O: a merge's rewrite must not drop a line appended meanwhile.
        self._local_log_lock = LocalLogLock()

    @contextmanager
    def _local_log_held(self, rewrite=False):
        """The local log lock: an append's share, or a *rewrite*'s whole.

        A rewrite waits at most :data:`LOCAL_LOCK_WAIT_SEC`, then raises (the
        next ship merges again). An append waits for a rewrite to finish —
        while :func:`finalizing`, at most as long, then goes on without it."""
        lock = self._local_log_lock
        if rewrite:
            if not lock.acquire_rewrite(LOCAL_LOCK_WAIT_SEC):
                raise RuntimeError("the local log is held by an interrupted thread")
            release = lock.release_rewrite
        elif lock.acquire_append(LOCAL_LOCK_WAIT_SEC if _FINALIZING.is_set() else None):
            release = lock.release_append
        else:
            VMN_LOGGER.debug("The local log is held by an interrupted rewrite")
            release = None
        try:
            yield
        finally:
            if release is not None:
                release()

    def _seed_local_log(self, app_name, verstr, writer_id):
        """Before this cache's first append under *writer_id*: when the remote
        holds more of the writer's log than the local copy, bring the local
        copy up to it. Tried once, outside the sync lock a ship holds across
        remote I/O: when it fails, the next ship merges the remote's lines in
        instead (the append path never waits on retries). Two first appends
        seeding at once rewrite the same lines."""
        key = (app_name, verstr, writer_id)
        if not self._local_is_replica or self._seed_tried(key):
            return
        try:
            if self.remote_for(app_name, verstr):
                self._catch_up_if_behind(app_name, verstr, writer_id)
        except Exception:
            VMN_LOGGER.debug("Could not compare the log with the remote", exc_info=True)
            self._seed_failed.add(key)
            return
        self._seeded.add(key)

    def _seed_tried(self, key):
        return key in self._seeded or key in self._seed_failed

    def _catch_up_if_behind(self, app_name, verstr, writer_id):
        objects = list(self._remote.log_objects(app_name, verstr, writer_id))
        local_size = self._local.log_sizes(app_name, verstr).get(writer_id, 0)
        if sum(size for _, size in objects) > local_size:
            self._catch_up(app_name, verstr, writer_id, objects)

    def _catch_up(self, app_name, verstr, writer_id, objects):
        """Rewrite the local log as the remote's *objects* of the writer, then
        the local lines they lack; returns the sync state past the remote's."""
        names = [name for name, _ in objects]
        bodies = parallel_map(lambda n: self._remote.load_file(app_name, verstr, n), names)
        if any(body is None for body in bodies):
            raise RuntimeError(f"{verstr}: the remote log of {writer_id!r} changed")
        remote = b"".join(bodies)
        base = log_object_name(writer_id)
        with self._local_log_held(rewrite=True):
            local = self._complete_lines(app_name, verstr, base, 0)
            self._local.save_file(app_name, verstr, base, _with_missing_lines(remote, local))
        return len(remote), next_seq(objects)

    def _needs_merge(self, key, offset, local_size):
        """Whether the local log of *key* may lack lines among the *offset*
        bytes the remote holds: its seed failed, or it no longer lines up with
        them — shorter, without its base file (other log files of the writer
        made up *local_size*), or with no line ending right there (a copy
        dropped and grown back, or grown without the remote's lines, almost
        always has a line cut there)."""
        if key in self._seed_failed:
            return True
        if not offset:
            return False
        if offset > local_size:
            return True
        app_name, verstr, writer_id = key
        name = log_object_name(writer_id)
        data = self._local.read_file_from(app_name, verstr, name, offset - 1)
        return not data or data[:1] != b"\n"

    def _merge_remote_lines(self, app_name, verstr, writer_id):
        """Merge the remote's lines of the writer into the local log, from a
        fresh listing; returns the sync state past the remote's."""
        objects = list(self._remote.log_objects(app_name, verstr, writer_id))
        state = self._catch_up(app_name, verstr, writer_id, objects)
        self._seed_failed.discard((app_name, verstr, writer_id))
        return state
