#!/usr/bin/env python3
"""Dumps written to ``<data-dir>/diag/diag-<UTC %Y%m%dT%H%M%SZ>-<pid>.json``:
on SIGUSR1 (from a short-lived thread, so a starved event loop does not
matter) and every ``--diag-every`` seconds (keeping the last :data:`KEEP`)."""
import json
import os
import signal
import sys
import threading
import time

from vmn_exp.core.best_effort import warn_once
from vmn_exp.storage.files import atomic_write
from vmn_exp.ui.diag.registry import build_dump
from vmn_exp.ui.server_logging import utc_stamp

KEEP = 20
DIR = "diag"
PREFIX = "diag-"


def dump_dir(data_dir):
    return os.path.join(data_dir, DIR)


def write_dump(data_dir):
    """Write one dump; returns its path."""
    directory = dump_dir(data_dir)
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = os.path.join(directory, f"{PREFIX}{stamp}-{os.getpid()}.json")
    atomic_write(path, json.dumps(build_dump(), indent=1, default=str))
    return path


def _write_and_log(data_dir):
    try:
        path = write_dump(data_dir)
    except Exception as exc:
        print(f"{utc_stamp()} vmn-exp ui: diagnostic dump failed: {exc!r}", file=sys.stderr,
              flush=True)
        return
    print(f"{utc_stamp()} vmn-exp ui: diagnostic dump written to {path}", file=sys.stderr,
          flush=True)


def install_signal_handler(data_dir):
    """Dump on SIGUSR1 (main thread only); returns the previous handler."""

    def on_signal(signum, frame):
        threading.Thread(target=_write_and_log, args=(data_dir,), daemon=True,
                         name="vmn-ui-diag-dump").start()

    return signal.signal(signal.SIGUSR1, on_signal)


def _prune(directory, keep=KEEP):
    names = sorted(n for n in os.listdir(directory)
                   if n.startswith(PREFIX) and n.endswith(".json"))
    for name in names[:-keep]:
        try:
            os.unlink(os.path.join(directory, name))
        except OSError:
            pass


def start_periodic_dumps(data_dir, every_sec, stop=None):
    """A daemon thread writing a dump every *every_sec* until *stop* is set."""
    stop = stop or threading.Event()

    def loop():
        while not stop.wait(every_sec):
            try:
                write_dump(data_dir)
                _prune(dump_dir(data_dir))
            except Exception as exc:
                warn_once("diag-periodic", f"Periodic diagnostic dump failed: {exc!r}")

    thread = threading.Thread(target=loop, daemon=True, name="vmn-ui-diag-every")
    thread.start()
    return thread
