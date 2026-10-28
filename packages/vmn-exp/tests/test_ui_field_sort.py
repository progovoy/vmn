"""Plan 28 FS: the board sorts by a row field, ``tags.<k>`` or ``params.<k>``
server-side, its orders moved across index generations like the metric
orders (a derived generation answers what a fresh cache answers), live
rows placed again per time bucket, and keyset paging over them."""
import datetime
import random

import pytest
from duration_fleet import DurationFleet, ended_after
from leaderboard_fleet import T0, running
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb

SORTS = ["duration_sec", "queue_sec", "duration_ratio", "status", "tags.kind", "params.opt",
         "stale_sec", "name"]
ORDERS = [None, "asc", "desc"]
QUERIES = [None, "queue_sec > 600", "duration_ratio > 1.2", 'tags.kind = "refit"']


@pytest.fixture
def clock(monkeypatch):
    at = {"now": T0}
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or at["now"])
    return at


def _verstrs(page):
    return [row["verstr"] for row in page["rows"]]


def _cases():
    return [dict(sort=s, order=o, query=q) for s in SORTS for o in ORDERS for q in QUERIES]


def _check_same(cache, snap):
    fresh = lb.LeaderboardCache()
    for params in _cases():
        mine = cache.page(snap, {}, limit=10**6, **params)
        theirs = fresh.page(snap, {}, limit=10**6, **params)
        assert mine["total"] == theirs["total"], params
        assert _verstrs(mine) == _verstrs(theirs), params


@pytest.mark.parametrize("seed", range(6))
def test_field_orders_moved_across_generations_equal_a_fresh_cache(clock, seed):
    fleet = DurationFleet(seed)
    fleet.seed_tree(T0)
    cache = lb.LeaderboardCache(size=512)
    rng = random.Random(seed)
    for _ in range(8):
        snap = fleet.snapshot()
        _check_same(cache, snap)
        fleet.churn(T0, rng.randrange(1, 6))


def _value(row, sort):
    if "." in sort:
        prefix, key = sort.split(".", 1)
        return (row.get(prefix) or {}).get(key)
    return row.get(sort)


@pytest.mark.parametrize("sort", ["duration_sec", "queue_sec", "tags.kind"])
def test_a_field_order_keeps_missing_values_last_both_ways(clock, sort):
    fleet = DurationFleet(1)
    fleet.seed_tree(T0)
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache()
    for order, reverse in (("asc", False), ("desc", True)):
        rows = cache.page(snap, {}, sort=sort, order=order, limit=10**6)["rows"]
        values = [_value(row, sort) for row in rows]
        present = [v for v in values if v is not None]
        assert present == sorted(present, reverse=reverse)
        assert values[len(present):] == [None] * (len(values) - len(present))


def test_live_rows_move_in_a_duration_order_as_time_passes(clock):
    fleet = DurationFleet(2)
    root = fleet.add(None, None, ended_after(T0, 10))
    slow = fleet.add(root, "trial", ended_after(T0, 300))
    live = fleet.add(root, "trial", running(T0))
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache(bucket_sec=2)

    def order():
        return _verstrs(cache.page(snap, {}, sort="duration_sec", order="desc", limit=10))

    clock["now"] = T0 + datetime.timedelta(seconds=30)
    assert order().index(slow) < order().index(live)
    clock["now"] = T0 + datetime.timedelta(seconds=40)  # the live run beats again
    fleet.set_state(fleet.index(live), running(clock["now"]))
    snap = fleet.snapshot()
    clock["now"] = T0 + datetime.timedelta(seconds=50)
    assert order().index(slow) < order().index(live)
    fleet.set_state(fleet.index(live), running(T0 + datetime.timedelta(seconds=400)))
    snap = fleet.snapshot()
    clock["now"] = T0 + datetime.timedelta(seconds=401)
    assert order()[:2] == [live, slow]


@pytest.mark.parametrize("sort", ["duration_sec", "tags.kind", "params.opt"])
def test_keyset_pages_over_a_field_order_cover_it_once(clock, sort):
    fleet = DurationFleet(4)
    fleet.seed_tree(T0)
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache()
    whole = _verstrs(cache.page(snap, {}, sort=sort, order="desc", limit=10**6))
    seen, cursor = [], None
    while True:
        page = cache.page(snap, {}, sort=sort, order="desc", limit=7, cursor=cursor)
        seen += _verstrs(page)
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == whole
