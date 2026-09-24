"""ui.memo.LRU: the shared bounded memo behind the ui's read caches."""
import threading
import time

from version_stamp.ui.memo import LRU


def _counting(value):
    calls = []

    def compute():
        calls.append(1)
        return value

    return compute, calls


def test_a_hit_does_not_recompute():
    lru = LRU(2)
    compute, calls = _counting("v")
    assert lru.get("k", compute) == "v"
    assert lru.get("k", compute) == "v"
    assert len(calls) == 1


def test_least_recently_used_is_evicted():
    lru = LRU(2)
    lru.get("a", lambda: 1)
    lru.get("b", lambda: 2)
    lru.get("a", lambda: 1)  # a is now the most recent
    lru.get("c", lambda: 3)
    compute, calls = _counting(1)
    lru.get("a", compute)
    assert calls == []
    compute, calls = _counting(2)
    lru.get("b", compute)
    assert calls == [1]


def test_store_predicate_keeps_rejected_values_out():
    lru = LRU(2)
    compute, calls = _counting((None, "boom"))
    rejected = lambda value: value[1] is None  # noqa: E731
    assert lru.get("k", compute, store=rejected) == (None, "boom")
    lru.get("k", compute, store=rejected)
    assert len(calls) == 2


def test_clear_drops_every_entry():
    lru = LRU(2)
    lru.get("k", lambda: 1)
    lru.clear()
    compute, calls = _counting(1)
    lru.get("k", compute)
    assert calls == [1]


def test_concurrent_misses_on_the_same_key_compute_once():
    """N threads racing a not-yet-cached key: one computes, the rest reuse it."""
    lru = LRU(2)
    calls = []

    def compute():
        calls.append(1)
        time.sleep(0.05)  # long enough for every other caller to arrive
        return object()

    results = [None] * 10

    def worker(i):
        results[i] = lru.get("k", compute)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1
    assert all(value is results[0] for value in results)


def test_concurrent_misses_on_different_keys_are_not_serialized():
    """A slow compute for one key must not block another key's compute."""
    lru = LRU(4)
    barrier = threading.Barrier(2, timeout=5)

    def compute(key):
        barrier.wait()  # both computes must be running at once
        return key

    results = {}

    def worker(key):
        results[key] = lru.get(key, lambda: compute(key))

    threads = [threading.Thread(target=worker, args=(key,)) for key in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == {"a": "a", "b": "b"}
