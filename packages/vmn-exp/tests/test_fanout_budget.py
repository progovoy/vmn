"""Concurrent object-store fan-outs share one bounded budget of workers, so
together they never hold more connections than the S3 client pools: each
runs on its caller's thread plus the spare workers the budget lends it (none
spare: in its caller alone, never waiting for one)."""
import threading
import time

from vmn_exp.core import series_reader
from vmn_exp.storage import fanout
from vmn_exp.storage.s3_base import MAX_POOL_CONNECTIONS, parallel_map

CALLERS = 8


class _InFlight:
    def __init__(self):
        self.now = self.most = 0
        self.lock = threading.Lock()

    def read(self, item):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)
        time.sleep(0.01)
        with self.lock:
            self.now -= 1
        return item


def _together(target):
    barrier = threading.Barrier(CALLERS)
    results = []

    def run():
        barrier.wait()
        results.append(target())

    threads = [threading.Thread(target=run) for _ in range(CALLERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_the_budget_leaves_the_pool_room_for_the_callers():
    assert fanout.SHARED_WORKERS <= MAX_POOL_CONNECTIONS // 2


def test_parallel_maps_at_once_stay_within_the_shared_budget(monkeypatch):
    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(4))
    flight = _InFlight()

    results = _together(lambda: parallel_map(flight.read, range(10)))

    assert results == [list(range(10))] * CALLERS
    assert flight.most <= CALLERS + 4


def test_series_segment_reads_share_the_budget(monkeypatch):
    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(4))
    flight = _InFlight()

    class Storage:
        def read_range(self, app, verstr, name, offset, length):
            return flight.read(b"")

    objects = [(f"metrics/w@{i:06d}.vms", 10) for i in range(10)]
    _together(lambda: series_reader._read_all(Storage(), "app", "v", objects))

    assert flight.most <= CALLERS + 4


def test_a_fan_out_with_nothing_spare_runs_in_its_caller(monkeypatch):
    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(0))
    threads = set()

    def read(item):
        threads.add(threading.current_thread().name)
        return parallel_map(lambda x: x * 2, [item, item])  # nested: no deadlock

    assert parallel_map(read, range(5)) == [[2 * i] * 2 for i in range(5)]
    assert threads == {threading.current_thread().name}


def test_lent_workers_go_back_to_the_budget(monkeypatch):
    slots = threading.Semaphore(3)
    monkeypatch.setattr(fanout, "_SLOTS", slots)

    parallel_map(lambda x: x, range(10))

    assert all(slots.acquire(blocking=False) for _ in range(3))
    assert not slots.acquire(blocking=False)
