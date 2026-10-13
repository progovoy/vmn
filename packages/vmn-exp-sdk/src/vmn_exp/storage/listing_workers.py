#!/usr/bin/env python3
"""Scan many local record directories in worker processes.

:class:`~vmn_exp.storage.listing.RecordListings` hands a very large full
listing here: ``(directory, settled listing it knows)`` items, split across
worker processes (:mod:`~vmn_exp.core.index_workers`' machinery) that each
run :func:`~vmn_exp.storage.listing.scan_dir` over their share and hand the
results back pickled. Best effort: a worker that fails to start or exits
non-zero leaves its items None, for the caller to scan in-process.
"""
import pickle
import sys

DIRS_PER_WORKER = 2500
MAX_WORKERS = 16


def scan_dirs(items, identity):
    """``scan_dir(path, known, identity)`` per ``(path, known)`` of *items*,
    None for those no worker answered (all of them when none can start)."""
    from vmn_exp.core import index_workers

    count = min(MAX_WORKERS, index_workers._cpus(), len(items) // DIRS_PER_WORKER)
    if count < 2 or not index_workers._can_spawn():
        return [None] * len(items)
    answers = index_workers.in_workers(items, count, lambda chunk: _run_worker(chunk, identity))
    found = [None] * len(items)
    for i, answer in enumerate(answers):
        if answer is not None:
            found[i::count] = answer
    return found


def _worker_command():
    from vmn_exp.core.index_workers import worker_command

    return worker_command(__name__)


def _run_worker(items, identity):
    """One worker's results for *items*, or None if it failed."""
    from vmn_exp.core.index_workers import run_in_worker

    return run_in_worker(_worker_command(), (items, identity))


def main():
    """Worker entry point: pickled ``(items, identity)`` on stdin, the
    results on stdout."""
    from vmn_exp.core.gc_pause import gc_paused
    from vmn_exp.storage.listing import scan_dir

    with gc_paused():  # everything it lists lives until it exits
        items, identity = pickle.load(sys.stdin.buffer)
        found = [scan_dir(path, known, identity) for path, known in items]
    pickle.dump(found, sys.stdout.buffer, pickle.HIGHEST_PROTOCOL)
    sys.stdout.buffer.flush()
