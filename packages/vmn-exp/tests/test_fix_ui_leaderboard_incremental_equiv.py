"""A generation derived from the previous one (only the changed rows
re-derived, re-filtered and re-placed) must answer exactly what a cache that
never saw an earlier generation answers for the same snapshot."""
import datetime
import random

import pytest

from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb

VOLATILE = ("stale_sec", "duration_sec")
SCHEMAS = [{}, {"loss": {"goal": "min", "primary": True}}, {"acc": {"goal": "max"}}]
SORTS = [None, "loss", "acc", "timestamp", "nope"]
ORDERS = [None, "asc", "desc"]
STATUSES = [None, "running", "stuck,failed", "succeeded,created"]
QUERIES = [None, 'status = "running"', 'tree_status = "stuck"', "metrics.loss < 0.6",
           'params.opt = "adam" or status != "failed"', 'kind = "outer"', "depth >= 1",
           'kind = "inner" and not tree_status = "succeeded"']


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _rows(result, strip):
    rows = result["rows"] if isinstance(result, dict) else result
    if not strip:
        return rows
    return [{k: v for k, v in r.items() if k not in VOLATILE} for r in rows]


def _variants(rng, count):
    fixed = [dict(sort=s, order=o) for s in SORTS for o in ORDERS]
    fixed += [dict(status=s) for s in STATUSES] + [dict(query=q) for q in QUERIES]
    fixed += [dict(archived=True, sort="loss"), dict(last=7, sort="loss"), dict(last=40)]
    for _ in range(count):
        fixed.append(dict(
            sort=rng.choice(SORTS), order=rng.choice(ORDERS), status=rng.choice(STATUSES),
            query=rng.choice(QUERIES), archived=rng.random() < 0.3,
            last=rng.choice([None, None, None, 5, 25]),
        ))
    return fixed


class _Annotations:
    """Counts full annotations while :attr:`on` (the cache under test only)."""

    def __init__(self, monkeypatch):
        self.calls, self.on = 0, False
        real = lb.annotate_rows

        def counted(*args, **kwargs):
            self.calls += self.on
            return real(*args, **kwargs)

        monkeypatch.setattr(lb, "annotate_rows", counted)


def _answers(cache, snap, cases):
    out = []
    for schema, params in cases:
        out.append((params, cache.page(snap, schema, limit=10**6, **params)))
        if not params.get("last"):
            cols = {k: v for k, v in params.items() if k != "last"}
            keys = ["metrics.loss", "status", "timestamp", "name"]
            out.append((params, cache.columns(snap, schema, keys, limit=50, **cols)))
    return out + [(a, cache.facets(snap, archived=a)) for a in (False, True)]


def _cases(seed):
    """The same requests every generation, so each order moves on from its last."""
    rng = random.Random(seed)
    return [(rng.choice(SCHEMAS), params) for params in _variants(rng, 12)]


def _assert_same(cache, snap, seed, strip, annotations=None):
    cases = _cases(seed)
    if annotations:
        annotations.on = True
    got = _answers(cache, snap, cases)
    if annotations:
        annotations.on = False
    want = _answers(lb.LeaderboardCache(bucket_sec=cache.bucket_sec), snap, cases)
    for (params, mine), (_, theirs) in zip(got, want):
        if "rows" in mine:
            assert mine["total"] == theirs["total"], params
            assert _rows(mine, strip) == _rows(theirs, strip), params
        else:
            assert mine == theirs, params


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize("clock", ["frozen", "moving"])
def test_derived_generations_equal_a_fresh_cache(monkeypatch, seed, clock):
    rng = random.Random(seed)
    now = T0
    _at(monkeypatch, now)
    fleet = Fleet(seed)
    fleet.seed(rng.randrange(150, 300), now)
    annotations = _Annotations(monkeypatch)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    for generation in range(8):
        if clock == "moving":
            now += datetime.timedelta(seconds=rng.choice([1, 7, 25, 61]))
            _at(monkeypatch, now)
        fleet.mutate(now, rng.randrange(1, 5))
        snap = fleet.snapshot()
        _assert_same(cache, snap, seed, strip=clock == "moving", annotations=annotations)
        if clock == "moving":
            # A later time bucket of the same generation re-derives the live rows.
            now += datetime.timedelta(seconds=rng.choice([3, 45]))
            _at(monkeypatch, now)
            _assert_same(cache, snap, seed, strip=True, annotations=annotations)
    # Every generation after the first was derived, never re-annotated.
    assert annotations.calls == 1


def test_many_live_rows_under_one_sweep_roll_up(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(3)
    roots = fleet.seed(200, T0, sweeps=2, live=30)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    rng = random.Random(3)
    _assert_same(cache, fleet.snapshot(), 7, strip=False)
    for step in range(1, 6):
        now = T0 + datetime.timedelta(seconds=20 * step)
        _at(monkeypatch, now)
        for _ in range(5):
            fleet.append(parent=rng.choice(roots), state=running(now, rng.choice([0, 70])))
        fleet.set_state(fleet.index(roots[0]), running(now))
        fleet.set_state(rng.randrange(len(fleet.specs)), finished(1))
        snap = fleet.snapshot()
        _assert_same(cache, snap, 7, strip=True)
        _at(monkeypatch, now + datetime.timedelta(seconds=65))
        _assert_same(cache, snap, 7, strip=True)


def test_a_large_delta_or_a_parent_cycle_still_matches(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(5)
    fleet.seed(120, T0)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    _assert_same(cache, fleet.snapshot(), 7, strip=False)

    fleet.remove(3)  # every later row moves: a delta larger than the snapshot's tenth
    _assert_same(cache, fleet.snapshot(), 7, strip=False)

    a, b = fleet.specs[10]["verstr"], fleet.specs[11]["verstr"]
    fleet.edit(10, parent=b)
    fleet.edit(11, parent=a)  # a two-run cycle
    _assert_same(cache, fleet.snapshot(), 7, strip=False)

    fleet.edit(11, parent=None)
    _assert_same(cache, fleet.snapshot(), 7, strip=False)


def test_two_lineages_of_the_same_app_name_never_mix(monkeypatch):
    _at(monkeypatch, T0)
    one, two = Fleet(1), Fleet(2)
    one.seed(150, T0)
    two.seed(150, T0)
    cache = lb.LeaderboardCache(bucket_sec=2)
    for _ in range(3):
        for fleet in (one, two):
            fleet.mutate(T0, 3, reparent=False)
            _assert_same(cache, fleet.snapshot(), 7, strip=False)
