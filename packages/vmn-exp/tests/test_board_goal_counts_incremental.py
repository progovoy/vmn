"""The board's per-metric goal counts are kept across index generations
(plan 32 follow-up): a run declaring, re-declaring or dropping a goal, or
leaving the store, moves its counts — checked against a full recount over
random generations."""
import random
from collections import Counter

from vmn_exp.core.fold import apply_entries, new_fold
from vmn_exp.core.index_snapshot import IndexSnapshot, RowCache
from vmn_exp.core.index_views import run_declared

APP = "app"
NAMES = ("loss", "acc", "val_*")
GOALS = ("min", "max", None)


def _record(i, rng):
    fold = new_fold()
    entries = [{"type": "metrics", "values": {"loss": 0.5}}]
    for name in rng.sample(NAMES, rng.randrange(len(NAMES) + 1)):
        goal, hidden = rng.choice(GOALS), rng.choice((True, None))
        entry = {"type": "define_metric", "name": name}
        entry.update({k: v for k, v in (("goal", goal), ("hidden", hidden)) if v is not None})
        entries.append(entry)
    apply_entries(fold, "w", 0, entries)
    return {
        "meta": {"verstr": f"0.0.1-dev.abc.r{i}", "timestamp": f"2026-01-01T00:00:{i % 60:02d}.{i:06d}Z",
                 "parent": None},
        "fold": fold, "rs_sig": [10, 1_800_000_000.0, "e"], "run_state": None,
    }


def _declared(order, records):
    """``{verstr: declared}`` straight from the records' folds."""
    found = ((records[k]["meta"]["verstr"], run_declared(records[k]["fold"])) for k in order)
    return {verstr: declared for verstr, declared in found if declared}


def _recount(declared_defs):
    counts = {}
    for declared in declared_defs.values():
        for name, fields in declared.items():
            if fields.get("goal"):
                counts.setdefault(name, Counter())[fields["goal"]] += 1
    return counts


def _rebuilt(snap, declared_defs):
    return IndexSnapshot.build(APP, snap.generation, snap.rows, {}, declared_defs=declared_defs)


def _generation(rng, order, records, serial):
    """Change, add or remove a few runs; ``(touched keys, next serial)``."""
    touched = set()
    for _ in range(rng.randrange(1, 4)):
        op = rng.random()
        if op < 0.6 and order:
            key = rng.choice(order)
            records[key] = _record(int(records[key]["meta"]["verstr"].rsplit("r", 1)[1]), rng)
            touched.add(key)
        elif op < 0.9:
            key = f"k{serial:05d}"
            order.append(key)
            records[key] = _record(serial, rng)
            touched.add(key)
            serial += 1
        elif order:
            key = order.pop(rng.randrange(len(order)))
            records.pop(key)
            touched.discard(key)
    return touched, serial


def test_goal_counts_match_a_full_recount_over_random_generations():
    for seed in range(20):
        rng = random.Random(seed)
        order = [f"k{i:05d}" for i in range(15)]
        records = {key: _record(i, rng) for i, key in enumerate(order)}
        cache, serial = RowCache(), len(order)
        snap = cache.snapshot(APP, 1, order, records)
        for gen in range(2, 40):
            touched, serial = _generation(rng, order, records, serial)
            for key in touched:
                cache.pop(key)  # as the index does for a changed record
            snap = cache.snapshot(APP, gen, list(order), records, touched)
            declared = _declared(order, records)
            assert snap.goal_counts() == _recount(declared), (seed, gen)
            assert snap.declared_schema() == _rebuilt(snap, declared).declared_schema(), (seed, gen)


def test_a_generation_without_a_declaration_change_shares_the_counts():
    rng = random.Random(1)
    order = [f"k{i:05d}" for i in range(10)]
    records = {key: _record(i, rng) for i, key in enumerate(order)}
    cache = RowCache()
    first = cache.snapshot(APP, 1, order, records)
    records[order[3]] = dict(records[order[3]], run_state={"state": "running"})
    second = cache.snapshot(APP, 2, order, records, {order[3]})
    assert second.goal_counts() is first.goal_counts()
