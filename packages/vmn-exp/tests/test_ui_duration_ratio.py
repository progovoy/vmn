"""Plan 28 N4: a board row's ``duration_ratio`` is its duration over the
median duration of its finished siblings (same parent, and the same value
of the app's split field when it has one), the elapsed time for a running
run (refreshed per time bucket), None with fewer than three finished
siblings; carried across index generations like the tree fields, sortable
and filterable."""
import datetime
import random
import statistics

import pytest
from duration_fleet import DurationFleet, ended_after
from leaderboard_fleet import T0, running
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.sibling_durations import MIN_SIBLINGS


@pytest.fixture
def clock(monkeypatch):
    at = {"now": T0}
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or at["now"])
    return at


def _ratios(cache, snap, split=None, **params):
    if split is not None:
        cache.bind_split(snap, split)
    rows = cache.page(snap, {}, limit=10**6, archived=True, **params)["rows"]
    return {row["verstr"]: row.get("duration_ratio") for row in rows}


def _close(got, want):
    return got is not None and abs(got - want) <= 0.02 * want


def _job(fleet, durations, kind="trial"):
    root = fleet.add(None, None, ended_after(T0, 5000))
    return root, [fleet.add(root, kind, ended_after(T0, d)) for d in durations]


def test_a_finished_run_is_compared_with_its_siblings_median(clock):
    fleet = DurationFleet(0)
    root, kids = _job(fleet, [100, 200, 300, 900])
    waiting = fleet.add(root, "trial", None)
    ratios = _ratios(lb.LeaderboardCache(), fleet.snapshot())
    median = statistics.median_high([100, 200, 300, 900])
    assert _close(ratios[kids[3]], 900 / median) and _close(ratios[kids[0]], 100 / median)
    assert ratios[root] is None  # top-level: no siblings
    assert ratios[waiting] is None  # no duration yet


def test_too_few_finished_siblings_give_no_ratio(clock):
    fleet = DurationFleet(0)
    _, kids = _job(fleet, [100] * (MIN_SIBLINGS - 1))
    assert {_ratios(lb.LeaderboardCache(), fleet.snapshot())[k] for k in kids} == {None}


def test_a_running_run_uses_its_elapsed_time_per_time_bucket(clock):
    fleet = DurationFleet(0)
    root, _ = _job(fleet, [100, 100, 100])
    live = fleet.add(root, "trial", running(T0))
    snap, cache = fleet.snapshot(), lb.LeaderboardCache(bucket_sec=2)
    clock["now"] = T0 + datetime.timedelta(seconds=20)
    assert _close(_ratios(cache, snap)[live], 0.2)
    clock["now"] = T0 + datetime.timedelta(seconds=50)
    assert _close(_ratios(cache, snap)[live], 0.5)
    assert _verstrs(cache, snap, sort="duration_ratio", order="desc")[0] != live
    assert _verstrs(cache, snap, query="duration_ratio < 0.6") == [live]


def _verstrs(cache, snap, **params):
    return [r["verstr"] for r in cache.page(snap, {}, limit=10**6, **params)["rows"]]


def test_the_split_field_compares_refits_with_refits(clock):
    fleet = DurationFleet(0)
    root, trials = _job(fleet, [100, 100, 100, 100])
    refits = [fleet.add(root, "refit", ended_after(T0, d)) for d in (1000, 1000, 3000)]
    snap = fleet.snapshot()
    by_parent = _ratios(lb.LeaderboardCache(), snap)
    by_kind = _ratios(lb.LeaderboardCache(), snap, split="tags.kind")
    assert _close(by_parent[refits[2]], 30) and _close(by_kind[refits[2]], 3)
    assert _close(by_kind[trials[0]], 1)


def test_a_sibling_finishing_moves_the_ratio_of_the_others(clock):
    fleet = DurationFleet(0)
    root, kids = _job(fleet, [100, 100, 900])
    cache = lb.LeaderboardCache()
    assert _close(_ratios(cache, fleet.snapshot())[kids[2]], 9)
    for _ in range(4):
        fleet.add(root, "trial", ended_after(T0, 900))
    snap = fleet.snapshot()
    assert _close(_ratios(cache, snap)[kids[0]], 100 / 900)
    assert _verstrs(cache, snap, query="duration_ratio < 0.5") == kids[:2]


def _check_same(cache, snap, split):
    fresh = lb.LeaderboardCache()
    assert _ratios(cache, snap, split) == _ratios(fresh, snap, split)
    for params in (dict(sort="duration_ratio", order="desc"), dict(sort="duration_ratio"),
                   dict(query="duration_ratio > 1.2"), dict(query="duration_ratio <= 1")):
        assert _verstrs(cache, snap, **params) == _verstrs(fresh, snap, **params), params


@pytest.mark.parametrize("split", [None, "tags.kind"])
@pytest.mark.parametrize("seed", range(6))
def test_ratios_carried_across_generations_equal_a_fresh_cache(clock, seed, split):
    fleet = DurationFleet(seed)
    fleet.seed_tree(T0)
    cache = lb.LeaderboardCache(size=512)
    rng = random.Random(seed)
    for _ in range(10):
        _check_same(cache, fleet.snapshot(), split)
        fleet.churn(T0, rng.randrange(1, 8))


def test_a_new_split_rebuilds_the_ratios(clock):
    fleet = DurationFleet(0)
    root, _ = _job(fleet, [100, 100, 100, 100])
    refit = fleet.add(root, "refit", ended_after(T0, 300))
    for _ in range(2):
        fleet.add(root, "refit", ended_after(T0, 300))
    snap, cache = fleet.snapshot(), lb.LeaderboardCache()
    assert _close(_ratios(cache, snap)[refit], 3)
    assert _close(_ratios(cache, snap, split="tags.kind")[refit], 1)
    fleet.add(root, "trial", ended_after(T0, 100))
    # A later generation of the app keeps the split its last request bound.
    assert _close(_ratios(cache, fleet.snapshot())[refit], 1)


def test_a_group_emptied_and_refilled_in_one_generation(clock):
    fleet = DurationFleet(0)
    root = fleet.add(None, None, ended_after(T0, 5000))
    only = fleet.add(root, "trial", ended_after(T0, 100))
    for _ in range(30):  # a delta small enough to move on from
        fleet.add(None, None, ended_after(T0, 50))
    cache = lb.LeaderboardCache()
    _ratios(cache, fleet.snapshot())
    fleet.edit(fleet.index(only), values={"loss": 0.5})  # the record changes
    snap = fleet.snapshot()
    assert _ratios(cache, snap) == _ratios(lb.LeaderboardCache(), snap)
