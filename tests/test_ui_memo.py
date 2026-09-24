"""ui.memo.LRU: the shared bounded memo behind the ui's read caches."""
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
