"""The direct-IO scanner behind the vmn-exp IO ratchet (test_io_boundary.py)."""
import textwrap

from io_scan import scan


def _scan(source):
    return dict(scan(textwrap.dedent(source)))


def test_counts_time_env_fs_subprocess_calls_by_kind():
    counts = _scan(
        """
        import os, subprocess, time, sqlite3, threading, uuid, socket

        def work(path):
            started = time.monotonic()
            time.sleep(1)
            home = os.environ.get("HOME")
            flag = os.getenv("FLAG")
            os.makedirs(path)
            with open(path) as handle:
                handle.read()
            subprocess.run(["true"])
            os.getpid()
            uuid.uuid4()
            socket.create_connection(("h", 1))
            sqlite3.connect(path)
            threading.Thread(target=work).start()
            print(started, home, flag)
        """
    )
    assert counts == {
        "time": 2,
        "env": 2,
        "fs": 2,
        "subprocess": 1,
        "process_self": 1,
        "random": 1,
        "net": 1,
        "sqlite": 1,
        "thread": 1,
        "console": 1,
    }


def test_real_default_argument_is_counted():
    counts = _scan(
        """
        import os, time

        def f(clock=time.time, *, env=os.environ):
            return clock(), env
        """
    )
    assert counts == {"real_default": 2}


def test_module_level_clock_alias_is_counted():
    counts = _scan(
        """
        import time

        _now = time.time
        _monotonic: object = time.monotonic
        """
    )
    assert counts == {"clock_alias": 2}


def test_from_import_and_import_as_are_resolved():
    counts = _scan(
        """
        import time as t
        from time import monotonic
        from time import sleep as nap
        from os import environ
        from datetime import datetime

        def f():
            t.time()
            monotonic()
            nap(1)
            datetime.now()
            return environ["X"]
        """
    )
    assert counts == {"time": 4, "env": 1}


def test_seeded_random_and_injected_calls_are_not_counted():
    counts = _scan(
        """
        import random

        class Job:
            def __init__(self, clock, seed):
                self._clock = clock
                self._rng = random.Random(seed)

            def tick(self, sleep):
                sleep(self._clock())
                return self._rng.random()
        """
    )
    assert counts == {}
