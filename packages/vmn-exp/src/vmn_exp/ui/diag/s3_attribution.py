#!/usr/bin/env python3
"""Who issued the S3 calls (an :func:`vmn_exp.storage.s3_stats.add_listener`
listener, :func:`install`).

A call made while serving a request (:func:`~vmn_exp.ui.diag.requests.
current_request`; store reads fanned out to pools carry the request's
context, :mod:`vmn_exp.storage.thread_context`) adds up on the request's
entry, ``entry.extra["s3"]``, which the ``requests`` section shows. Any
other call adds up on its thread's name with a pool worker number dropped
(``ThreadPoolExecutor-3_7`` -> ``ThreadPoolExecutor-3``), the
``s3.by_thread`` table: at most :data:`MAX_THREADS` names, the rest
:data:`OTHER`. Each table is ``{operation: {"n", "ms", "err"}}``.
"""
import re
import threading

from vmn_exp.storage import s3_stats
from vmn_exp.ui.diag.requests import current_request

MAX_THREADS = 50
OTHER = "(other)"
_WORKER_NUMBER = re.compile(r"_\d+$")

_lock = threading.Lock()
_threads = {}  # thread label -> OpTable


class OpTable:
    """Calls, total milliseconds and errors per operation."""

    __slots__ = ("ops",)

    def __init__(self):
        self.ops = {}  # operation -> [n, ms, err]

    def add(self, call):
        cell = self.ops.get(call.operation)
        if cell is None:
            cell = self.ops[call.operation] = [0, 0.0, 0]
        cell[0] += 1
        cell[1] += call.duration_ms
        if call.error:
            cell[2] += 1

    def snapshot(self):
        with _lock:
            return {op: {"n": n, "ms": round(ms, 1), "err": err}
                    for op, (n, ms, err) in sorted(self.ops.items())}


def thread_label(name):
    return _WORKER_NUMBER.sub("", name)


def record(call):
    entry = current_request()
    if entry is not None:
        table = entry.extra.get("s3") or entry.extra.setdefault("s3", OpTable())
        with _lock:
            table.add(call)
        return
    label = thread_label(threading.current_thread().name)
    with _lock:
        table = _threads.get(label)
        if table is None:
            if len(_threads) >= MAX_THREADS:
                label = OTHER
                table = _threads.get(label)
            if table is None:
                table = _threads[label] = OpTable()
        table.add(call)


def by_thread():
    with _lock:
        tables = list(_threads.items())
    return {label: table.snapshot() for label, table in tables}


def install():
    """Listen to every S3 call, once however often it is called."""
    s3_stats.remove_listener(record)
    s3_stats.add_listener(record)


def s3_section():
    """The ``s3`` section: :func:`~vmn_exp.storage.s3_stats.s3_stats` plus
    ``by_thread``."""
    return {**s3_stats.s3_stats(), "by_thread": by_thread()}
