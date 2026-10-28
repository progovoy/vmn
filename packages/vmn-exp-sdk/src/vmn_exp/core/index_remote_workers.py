#!/usr/bin/env python3
"""Load a remote cold index's records in long-lived worker processes.

A remote record costs four or so GETs, and each GET about 0.7 ms of
botocore CPU under the GIL; with the fold and the YAML that is ~4 ms of one
core per record, which capped a cold S3 load near 200 runs/s however many
threads waited on the network. So while a load has many records to go
(:meth:`ExperimentIndex._backlog`), a backend that says how to open itself
again (``worker_spec()``: an importable class and its arguments) has its new
records read by :data:`WORKERS` processes, each with its own client and
:data:`THREADS` requests in flight, and handing the records back pickled
(:func:`~vmn_exp.core.index_record.refresh_record`'s results, as the local
workers of :mod:`~vmn_exp.core.index_workers` do). The pickles are decoded
on the caller's thread, which owns the records (plan 26 decision 3).

Workers are started on first use and stay up between chunks
(:meth:`RemoteLoaders.close` ends them; one that fails is dropped). Best
effort: whatever a worker cannot load the caller loads in-process — but a
record the store refused (:func:`~vmn_exp.core.index_unreadable.store_failed`)
is set aside as the caller would, not read again at the store that refused
it, and a record set aside is left to the caller's due retry.
"""
import importlib
import os
import pickle
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from vmn_exp._base import ensure_logger
from vmn_exp.core.index_record import refresh_record, update_record
from vmn_exp.core.index_unreadable import StoreRefused, store_failed
from vmn_exp.core.index_io_process import _read, _read_raw as _receive_raw
from vmn_exp.core.index_io_process import _write as _send
from vmn_exp.core.index_workers import _can_spawn, _cpus, _spawn, worker_command

WORKERS = 4  # at most, and at most a CPU each but one
THREADS = 16  # requests a worker keeps in flight
MIN_RECORDS = 64  # a batch worth handing out
_SET_ASIDE = (None, False, False, False)  # a new record's refresh result once set aside


def worker_count():
    return max(0, min(WORKERS, _cpus() - 1)) if _can_spawn() else 0


class _Worker:
    def __init__(self, spec):
        self._proc = _spawn(worker_command(__name__), dict(os.environ))
        _send(self._proc.stdin, spec)

    def ask(self, request):
        """The raw pickled answer to *request*; raises when the worker died."""
        _send(self._proc.stdin, request)
        return _receive_raw(self._proc.stdout)

    def close(self):
        try:
            self._proc.stdin.close()
            self._proc.wait(5)
        except Exception:
            self._proc.kill()


class RemoteLoaders:
    """Worker processes reading *spec*'s records (see the module doc)."""

    def __init__(self, spec, count):
        self._spec, self._count = spec, count
        self._workers = None
        self._lock = threading.Lock()

    def load(self, app_name, work, unreadable=None):
        """``{key: refresh_record result}`` of *work*'s new records
        (``[(key, names, record)]``) not in *unreadable*, as far as the
        workers loaded them; those the store refused join *unreadable*
        (without one, they are left to the caller)."""
        new = [(key, names) for key, names, record in work
               if record is None and key not in (unreadable or ())]
        workers = self._started() if len(new) >= MIN_RECORDS else []
        if not workers:
            return {}
        shares = [new[i::len(workers)] for i in range(len(workers))]
        with ThreadPoolExecutor(len(workers), thread_name_prefix="vmn-index-remote") as pool:
            raws = list(pool.map(self._ask, workers, [(app_name, s) for s in shares]))
        done = {}
        for raw in raws:
            if raw is not None:
                done.update(_loaded(pickle.loads(raw), unreadable))
        return done

    def _ask(self, worker, request):
        try:
            return worker.ask(request)
        except Exception:
            self._drop(worker)
            return None

    def _started(self):
        with self._lock:
            if self._workers is None:
                self._workers = []
                for _ in range(self._count):
                    try:
                        self._workers.append(_Worker(self._spec))
                    except Exception:
                        break
            return list(self._workers)

    def _drop(self, worker):
        with self._lock:
            if self._workers and worker in self._workers:
                self._workers.remove(worker)
        worker.close()

    def close(self):
        with self._lock:
            workers, self._workers = self._workers or [], None
        for worker in workers:
            worker.close()


def _loaded(answers, unreadable):
    """The ``(key, result)`` of a worker's *answers* to keep: a record the
    store refused is set aside in *unreadable*, without one left out."""
    for key, result in answers:
        if isinstance(result, StoreRefused):
            if unreadable is not None:
                unreadable.failed(key, result)
                yield key, _SET_ASIDE
        elif result:
            yield key, result


def _open(spec):
    module, name, args, kwargs = spec
    return getattr(importlib.import_module(module), name)(*args, **kwargs)


def _load(storage, app_name, items):
    direct_of = getattr(storage, "direct_files", None)
    direct = direct_of() if direct_of else storage

    def one(item):
        key, names = item
        try:
            return key, refresh_record(
                key, names, None, lambda *a: update_record(storage, direct, app_name, *a))
        except Exception as exc:
            # The caller loads it, meeting any real error — unless the store refused it.
            return key, StoreRefused.of(exc) if store_failed(exc) else None

    with ThreadPoolExecutor(THREADS, thread_name_prefix="vmn-index-remote") as pool:
        return list(pool.map(one, items))


def main():
    """Worker entry point: a pickled spec, then ``(app, items)`` requests,
    each answered with ``[(key, result or StoreRefused or None)]``
    (length-prefixed pickles)."""
    ensure_logger()
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    storage = _open(_read(stdin))
    while True:
        try:
            app_name, items = _read(stdin)
        except EOFError:
            return
        _send(stdout, _load(storage, app_name, items))
