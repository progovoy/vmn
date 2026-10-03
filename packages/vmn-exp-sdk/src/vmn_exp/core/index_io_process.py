#!/usr/bin/env python3
"""Do an :mod:`experiment_index`'s filesystem work in a helper process.

A server thread that ``stat``s, ``open``s or steps SQLite gives the GIL up
for each call and — while request threads keep the interpreter busy — waits
up to a switch interval (5ms) to get it back. A refresh at 100k records makes
~100k such calls, so under load one refresh took minutes and new runs never
reached the dashboard, while the same refresh on an idle server took 1s.

So a server's index (:meth:`ExperimentIndex.use_io_process`) hands the work
to a helper: a fresh interpreter running :func:`main` over the same plain
local store and SQLite file, with an in-process index of its own as the
toolbox — its listing watch reports changes, its refresh reads records and
persists them. The server's process only exchanges pickles with it: the
listings' changes, the records a refresh touches (the ones the listing shows
unchanged are never sent) and what came back. Responses stream in chunks, so
a cold load of 100k records never sits in one buffer.

The helper exits when its stdin closes (the server died). A call that finds
it dead or failing raises :class:`IOProcessError`, failing that refresh; the
next call starts a new helper, whose listings then report everything again.
"""
import logging
import os
import pickle
import struct
import subprocess
import sys
import traceback

from vmn_exp.core.index_record import listed_unchanged
from vmn_exp.core.index_workers import _can_spawn

_LOGGER = logging.getLogger(__name__)
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HEADER = struct.Struct("!Q")
_CHUNK = 2000  # records per streamed response part


class IOProcessError(Exception):
    """The I/O helper process died or failed a call."""


def start_io_process(storage, app_name, cache_path):
    """A running :class:`ProcessIO` for *storage*, or None when it is not a
    plain local store or no helper could start."""
    args = _plain_local_args(storage)
    if args is None or not _can_spawn():
        return None
    try:
        return ProcessIO(args, app_name, cache_path)
    except (OSError, IOProcessError):
        _LOGGER.debug("Could not start the index I/O helper", exc_info=True)
        return None


def _plain_local_args(storage):
    is_remote = getattr(storage, "is_remote", None)
    if is_remote and is_remote():
        return None
    direct_files = getattr(storage, "direct_files", None)
    direct = direct_files() if direct_files else storage
    args_of = getattr(direct, "io_process_args", None)
    return args_of() if args_of else None


def _write(stream, obj):
    data = pickle.dumps(obj, pickle.HIGHEST_PROTOCOL)
    stream.write(_HEADER.pack(len(data)) + data)
    stream.flush()


def _read(stream):
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        raise EOFError
    (size,) = _HEADER.unpack(header)
    data = stream.read(size)
    if len(data) < size:
        raise EOFError
    return pickle.loads(data)


class _Watch:
    """The helper's :class:`~vmn_exp.core.index_listing.ListingWatch`."""

    # One full listing at 100k records keeps a refresh busy for seconds.
    rolling = True

    def __init__(self, io):
        self._io = io

    def name_changes(self):
        return self._io.call("name_changes")

    def files(self, keys):
        return self._io.call("files", list(keys)) if keys else {}

    def full_changes(self):
        return self._io.call("full_changes")

    def slice_changes(self, keys):
        return self._io.call("slice_changes", list(keys)) if keys else ({}, set())

    def reset(self):
        # A replaced helper starts from empty baselines anyway.
        if self._io.alive():
            self._io.call("reset")


class ProcessIO:
    def __init__(self, args, app_name, cache_path):
        self._setup = (args, app_name, cache_path)
        self._proc = None
        self.watch = _Watch(self)
        self._start()

    def _start(self):
        cmd = [
            sys.executable, "-c",
            f"import sys; sys.path.insert(0, {_PACKAGE_ROOT!r}); "
            "from vmn_exp.core.index_io_process import main; main()",
        ]
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        try:
            self.call("setup", *self._setup)
        except IOProcessError:
            self._discard()
            raise

    def alive(self):
        return self._proc is not None and self._proc.poll() is None

    def call(self, op, *args):
        """*op*'s answer from the helper. One found dead fails this call; the
        next starts a new helper."""
        if self._proc is None:
            self._start()
        elif self._proc.poll() is not None:
            self._proc = None
            raise IOProcessError("index I/O helper exited")
        try:
            _write(self._proc.stdin, (op, args))
            parts = []
            while True:
                status, payload = _read(self._proc.stdout)
                if status == "part":
                    parts.extend(payload)
                elif status == "ok":
                    return parts + payload if parts else payload
                else:
                    raise IOProcessError(f"index I/O helper failed {op}: {payload}")
        except (OSError, EOFError, pickle.UnpicklingError) as exc:
            self._discard()
            raise IOProcessError(f"index I/O helper died during {op}") from exc

    def load(self):
        return dict(self.call("load"))

    def refresh(self, work, removed):
        """Like the in-process refresh, but a record the listing shows
        unchanged is neither sent nor returned (None)."""
        send = [w for w in work if w[2] is None or not listed_unchanged(w[2], w[1])]
        results = {r[0]: r for r in self.call("refresh", send, list(removed))} if send or removed else {}
        return [results.get(key, (key, None, False, False, False)) for key, _, _ in work]

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.wait(10)
            except (OSError, subprocess.TimeoutExpired):
                self._proc.kill()
                self._proc.wait()
            self._proc = None

    def kill_for_tests(self):
        """Kill the helper as a crash would."""
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait()

    def _discard(self):
        self.kill_for_tests()
        self._proc = None


# -- the helper process --------------------------------------------------------


def _changed_results(results, sent):
    """Results with the records the refresh left as they came replaced by None."""
    out = []
    for key, record, dirty, moved, state_moved in results:
        if not (dirty or moved or state_moved) and pickle.dumps(record) == sent.get(key):
            record = None
        out.append((key, record, dirty, moved, state_moved))
    return out


class _Helper:
    def __init__(self, args, app_name, cache_path):
        from vmn_exp.core.index import ExperimentIndex
        from vmn_exp.storage.local import LocalSnapshotStorage

        self.index = ExperimentIndex(LocalSnapshotStorage(*args), app_name, cache_path)
        self.watch = self.index._sweep.watch

    def load(self):
        return list(self.index._store.load(self.index.app_name).items())

    def refresh(self, work, removed):
        sent = {key: pickle.dumps(record) for key, _, record in work if record is not None}
        return _changed_results(self.index._refresh_and_persist(work, removed), sent)


def _answer(out, result):
    if isinstance(result, list):
        while len(result) > _CHUNK:
            _write(out, ("part", result[:_CHUNK]))
            result = result[_CHUNK:]
    _write(out, ("ok", result))


def main():
    """Helper entry point: ``(op, args)`` requests on stdin, answers on stdout."""
    inp = sys.stdin.buffer
    # Answers go to a private copy of stdout; anything else printed goes to stderr.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    helper = None
    while True:
        try:
            op, args = _read(inp)
        except EOFError:
            return
        try:
            if op == "setup":
                helper, result = _Helper(*args), None
            elif op in ("load", "refresh"):
                result = getattr(helper, op)(*args)
            else:
                result = getattr(helper.watch, op)(*args)
            _answer(out, result)
        except Exception:
            _write(out, ("err", traceback.format_exc(limit=5)))
