"""Concurrent CacheTidy.tick() calls (request threads) start one tidy and
never raise ``RuntimeError: thread already started``."""
import threading
from types import SimpleNamespace

from vmn_exp.ui import cache_tidy
from vmn_exp.ui.cache_tidy import CacheTidy


def _meet(barrier):
    try:
        barrier.wait(timeout=0.5)
    except threading.BrokenBarrierError:
        pass  # the other tick is held back (by the fix's lock)


class _FinishedTidy:
    """The last tidy, done: both ticks ask it at once whether it still runs."""

    def __init__(self, barrier):
        self._barrier = barrier

    def is_alive(self):
        _meet(self._barrier)
        return False

    def join(self, timeout=None):
        pass


class _CountingThread(threading.Thread):
    started = []
    barrier = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _meet(_CountingThread.barrier)  # both ticks build theirs before either starts

    def start(self):
        _CountingThread.started.append(self)
        super().start()


def _tick_concurrently(tidy, n=2):
    errors = []

    def tick():
        try:
            tidy.tick()
        except Exception as exc:  # the 500 the request got
            errors.append(exc)

    ticks = [threading.Thread(target=tick, daemon=True) for _ in range(n)]
    for t in ticks:
        t.start()
    for t in ticks:
        t.join(10)
    return errors


def test_concurrent_ticks_start_one_tidy(tmp_path, monkeypatch):
    monkeypatch.setattr(CacheTidy, "_tidy", lambda self: None)
    tidy = CacheTidy(str(tmp_path / "cache.sqlite"), clock=lambda: 100.0)
    tidy._thread = _FinishedTidy(threading.Barrier(2))
    _CountingThread.started, _CountingThread.barrier = [], threading.Barrier(2)
    monkeypatch.setattr(cache_tidy, "threading",
                        SimpleNamespace(Thread=_CountingThread))

    errors = _tick_concurrently(tidy)
    tidy.wait(5)

    assert errors == []
    assert len(_CountingThread.started) == 1
