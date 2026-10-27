"""A request's fan-out keeps workers of its own: background fan-outs (an index
load's folds, upkeep) may take every slot they can borrow, and a run page's
segment reads then ran one by one in their request thread (2,000 segments at
~60 ms each: a 2-minute first view). Workers reserved for requests are never
lent to background fan-outs, and the total stays within the shared budget."""
import threading
import time

from vmn_exp.storage import fanout
from vmn_exp.storage.s3_base import parallel_map


def _thread_names(items):
    names = set()

    def read(item):
        names.add(threading.current_thread().name)
        time.sleep(0.01)
        return item

    return names, read


def test_a_request_fan_out_gets_workers_when_background_holds_the_rest(monkeypatch):
    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(0))  # background took all
    names, read = _thread_names(range(8))

    with fanout.serving_request():
        assert parallel_map(read, range(8)) == list(range(8))

    assert len(names) > 1


def test_a_background_fan_out_never_borrows_the_request_workers(monkeypatch):
    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(0))
    names, read = _thread_names(range(8))

    assert parallel_map(read, range(8)) == list(range(8))

    assert names == {threading.current_thread().name}


def test_the_request_workers_come_out_of_the_shared_budget():
    background = fanout._SLOTS._value
    requests = fanout._REQUEST_SLOTS._value

    assert requests >= 16
    assert background + requests == fanout.SHARED_WORKERS


def test_a_request_fan_out_returns_what_it_borrowed(monkeypatch):
    slots, request_slots = threading.Semaphore(2), threading.Semaphore(3)
    monkeypatch.setattr(fanout, "_SLOTS", slots)
    monkeypatch.setattr(fanout, "_REQUEST_SLOTS", request_slots)

    with fanout.serving_request():
        parallel_map(lambda x: x, range(10))

    assert slots._value == 2
    assert request_slots._value == 3


def test_the_request_mark_reaches_the_fan_out_on_a_pool_thread(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from vmn_exp.storage.thread_context import in_caller_context

    monkeypatch.setattr(fanout, "_SLOTS", threading.Semaphore(0))
    names, read = _thread_names(range(8))

    with fanout.serving_request(), ThreadPoolExecutor(1) as pool:
        pool.submit(in_caller_context(lambda: parallel_map(read, range(8)))).result()

    assert len(names) > 1
