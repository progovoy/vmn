"""A :class:`SharedMap` is a read-only mapping that generations share: a
frozen base plus an overlay of what changed since. Deriving the next
generation costs what changed, not the map's size; the overlay folds into a
new base once it passes FOLD_FRACTION of it (plan 26 F00)."""
import random
import tracemalloc

import pytest

from vmn_exp.core import shared_map
from vmn_exp.core.shared_map import SharedMap


def _random_stream(rng, keys, steps, per_step):
    for _ in range(steps):
        changes, removed = {}, set()
        for _ in range(per_step):
            key = rng.choice(keys)
            if rng.random() < 0.2:
                removed.add(key)
                changes.pop(key, None)
            else:
                changes[key] = rng.random()
                removed.discard(key)
        yield changes, removed


def _apply(ref, changes, removed):
    ref.update(changes)
    for key in removed:
        ref.pop(key, None)


def _check(m, ref):
    assert len(m) == len(ref)
    assert dict(m) == ref
    assert dict(m.items()) == ref
    assert sorted(m.values(), key=repr) == sorted(ref.values(), key=repr)
    assert set(m) == set(ref)
    for key in list(ref)[:50]:
        assert key in m and m[key] == ref[key] and m.get(key) == ref[key]
    assert m.get("absent", "dflt") == "dflt" and "absent" not in m
    with pytest.raises(KeyError):
        m["absent"]


def test_it_reads_like_its_dict_under_random_changes():
    rng = random.Random(7)
    keys = [f"k{i}" for i in range(300)]
    ref = {k: 0 for k in keys[:200]}
    m = SharedMap(dict(ref))
    for changes, removed in _random_stream(rng, keys, 400, 6):
        m = m.derive(changes, removed)
        _apply(ref, changes, removed)
        _check(m, ref)


def test_an_earlier_generation_never_sees_later_changes():
    first = SharedMap({"a": 1, "b": 2})
    second = first.derive({"a": 10, "c": 3}, {"b"})
    third = second.derive({"b": 20}, {"c"})
    assert dict(first) == {"a": 1, "b": 2}
    assert dict(second) == {"a": 10, "c": 3}
    assert dict(third) == {"a": 10, "b": 20}


def test_it_iterates_in_the_base_order_then_the_overlay_additions(monkeypatch):
    monkeypatch.setattr(shared_map, "FOLD_FRACTION", 10.0)  # never fold
    m = SharedMap({"a": 1, "b": 2, "c": 3})
    m = m.derive({"b": 20, "d": 4}).derive({"e": 5, "a": 10}, {"c"}).derive({"f": 6})
    assert list(m) == ["a", "b", "d", "e", "f"]
    assert list(m.items()) == [("a", 10), ("b", 20), ("d", 4), ("e", 5), ("f", 6)]


def test_a_fold_keeps_the_order_and_the_contents():
    rng = random.Random(3)
    keys = [f"k{i}" for i in range(2000)]
    ref = {k: 0 for k in keys[:1000]}
    m = SharedMap(dict(ref))
    for _ in range(60):  # past FOLD_FRACTION several times
        changes = {rng.choice(keys): rng.random() for _ in range(20)}
        before = [k for k in m if k in ref]
        m = m.derive(changes)
        _apply(ref, changes, ())
        assert list(m)[: len(before)] == before
        _check(m, ref)
    assert m.overlay_len <= shared_map.FOLD_FRACTION * len(m) + 20


def test_it_builds_from_a_base_overlay_and_removed_keys():
    m = SharedMap({"a": 1, "b": 2}, {"c": 3, "a": 5}, {"b"})
    assert dict(m) == {"a": 5, "c": 3}
    assert len(m) == 2


def test_it_is_a_mapping_not_a_dict():
    m = SharedMap({"a": 1})
    assert m == {"a": 1}
    assert not isinstance(m, dict)
    with pytest.raises(TypeError):
        m["a"] = 2


def _retained(build):
    """Bytes still allocated after *build()*, its result kept alive."""
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        kept = build()
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    del kept
    return after - before


@pytest.mark.parametrize("size", [10_000, 100_000])
def test_a_derive_costs_its_changes_not_the_map_size(size):
    base = SharedMap({f"run{i}": i for i in range(size)})
    changes = {f"run{i}": -i for i in range(0, size, size // 40)}
    assert _retained(lambda: base.derive(changes)) < 20_000


def test_folding_is_amortized_over_the_changes():
    """100 generations of 50 changes to a 50k map keep a small fraction of
    the bytes 100 dict copies would."""
    size, rng = 50_000, random.Random(11)
    m = SharedMap({f"run{i}": i for i in range(size)})
    one_copy = _retained(lambda: dict(m))

    def generations():
        kept, current = [], m
        for _ in range(100):
            current = current.derive({f"run{rng.randrange(size)}": rng.random()
                                      for _ in range(50)})
            kept.append(current)
        return kept

    assert _retained(generations) <= 0.02 * 100 * one_copy
