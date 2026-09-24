#!/usr/bin/env python3
"""Load a cold :mod:`experiment_index`'s new records in worker processes.

A cold build parses every record's ``metadata.yml``, log and ``run_state.yml``
— CPU-bound Python (the YAML constructor, the fold) that threads cannot share
out, about a third of a millisecond per record. So when a build has at least
``MIN_RECORDS`` new records of a plain local store, they are split across
worker processes that load them with the index's own code
(:func:`~version_stamp.core.experiment_index_record.refresh_record`) over the
same files and hand the records back pickled.

Workers are fresh interpreters running this module — not ``multiprocessing``,
whose spawn re-runs the caller's main script — importing this very package.
Best effort throughout: a worker that fails to start, exits non-zero or cannot
load a record leaves those records to the caller, which loads them in-process
(and meets any real error there, as it always did).
"""
import functools
import os
import pickle
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from version_stamp.core.experiment_index_record import refresh_record, update_record
from version_stamp.core.logging import ensure_logger
from version_stamp.core.record_files import RecordFiles

MIN_RECORDS = 1000  # below this, starting processes costs more than it saves
RECORDS_PER_WORKER = 500
MAX_WORKERS = 8
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_new_records(storage, direct, app_name, work):
    """``{key: refresh_record result}`` for the new records of *work*
    (``[(key, names, record)]``) loaded by workers; ``{}`` when not worth it."""
    new = [(key, names) for key, names, record in work if record is None]
    if len(new) < MIN_RECORDS or not _can_spawn():
        return {}
    count = min(MAX_WORKERS, _cpus(), len(new) // RECORDS_PER_WORKER)
    items = _with_record_dirs(storage, direct, app_name, new) if count > 1 else None
    if not items:
        return {}
    chunks = [items[i::count] for i in range(count)]
    with ThreadPoolExecutor(max_workers=count) as pool:
        answers = list(pool.map(lambda chunk: _run_worker(app_name, chunk), chunks))
    return {key: result for answer in answers for key, result in answer if result}


def _can_spawn():
    # An embedding host (uwsgi, a frozen app) is no interpreter to run -c with.
    name = os.path.basename(sys.executable or "").lower()
    return name.startswith(("python", "pypy")) and not getattr(sys, "frozen", False)


def _with_record_dirs(storage, direct, app_name, new):
    """``[(key, record dir, names)]`` for *new*, or None when a plain file
    read of the record directories is not what the storage would do."""
    is_remote = getattr(storage, "is_remote", None)
    record_dir = getattr(direct, "plain_record_dir", None)
    if record_dir is None or (is_remote and is_remote()):
        return None
    items = []
    for key, names in new:
        path = record_dir(app_name, key)
        if path is None:
            return None
        items.append((key, path, names))
    return items


def _cpus():
    affinity = getattr(os, "sched_getaffinity", None)
    return len(affinity(0)) if affinity else os.cpu_count() or 1


def _worker_command():
    return [
        sys.executable,
        "-c",
        f"import sys; sys.path.insert(0, {_PACKAGE_ROOT!r}); "
        "from version_stamp.core.experiment_index_workers import main; main()",
    ]


def _spawn(cmd, env):
    return subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env
    )


def _run_worker(app_name, chunk):
    """``[(key, result or None)]`` from one worker; ``[]`` if it failed."""
    try:
        proc = _spawn(_worker_command(), dict(os.environ))
        out, _ = proc.communicate(pickle.dumps((app_name, chunk), pickle.HIGHEST_PROTOCOL))
        return pickle.loads(out) if proc.returncode == 0 else []
    except Exception:
        return []


def _load_chunk(app_name, chunk):
    files = RecordFiles({key: path for key, path, _ in chunk})
    update = functools.partial(update_record, files, files, app_name)
    answers = []
    for key, _, names in chunk:
        try:
            result = refresh_record(key, names, None, update)
        except Exception:
            result = None  # e.g. a log that vanished mid-read: the caller retries
        answers.append((key, result))
    return answers


def main():
    """Worker entry point: a pickled ``(app, chunk)`` on stdin, answers on stdout."""
    ensure_logger()
    app_name, chunk = pickle.load(sys.stdin.buffer)
    pickle.dump(_load_chunk(app_name, chunk), sys.stdout.buffer, pickle.HIGHEST_PROTOCOL)
    sys.stdout.buffer.flush()
