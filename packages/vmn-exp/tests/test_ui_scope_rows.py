"""Plan 23 S2: every board row carries ``root`` (its top-level ancestor, null
for a top-level run) and ``failure_sig`` (null unless failed/stuck), right
across index generations derived by deltas — re-parenting included — and
across time buckets that turn a live run stuck."""
import datetime
import random

import pytest
from leaderboard_fleet import T0, Fleet, running
from vmn_exp.core import status as status_mod
from vmn_exp.core.tree import annotate_rows
from vmn_exp.ui.failure_signature import signature
from vmn_exp.ui.leaderboard_cache import LeaderboardCache


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _root(fleet, verstr):
    chain = fleet.ancestors(verstr)
    return chain[-1] if chain else None


def _check(cache, fleet, snap):
    rows = cache.page(snap, {}, limit=10**6, archived=True)["rows"]
    assert len(rows) == len(fleet.specs)
    for row in rows:
        assert row["root"] == _root(fleet, row["verstr"]), row["verstr"]
        assert row["failure_sig"] == signature(row), row["verstr"]
    return rows


@pytest.mark.parametrize("seed", range(6))
def test_root_and_failure_sig_match_a_brute_force_walk(monkeypatch, seed):
    rng = random.Random(seed)
    now = T0
    _at(monkeypatch, now)
    fleet = Fleet(seed)
    fleet.seed(rng.randrange(150, 300), now)
    cache = LeaderboardCache(bucket_sec=2)
    _check(cache, fleet, fleet.snapshot())
    for _ in range(8):
        now += datetime.timedelta(seconds=rng.choice([1, 7, 61]))
        _at(monkeypatch, now)
        fleet.mutate(now, rng.randrange(1, 6))
        snap = fleet.snapshot()
        _check(cache, fleet, snap)
        _at(monkeypatch, now + datetime.timedelta(seconds=120))  # live runs go stuck
        _check(cache, fleet, snap)


def test_relinking_a_job_moves_its_whole_subtree_to_the_new_root(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(1)
    one, two = fleet.append(), fleet.append()
    job = fleet.append(parent=one)
    kids = [fleet.append(parent=job) for _ in range(5)]
    for _ in range(100):
        fleet.append()
    cache = LeaderboardCache()
    rows = {r["verstr"]: r for r in _check(cache, fleet, fleet.snapshot())}
    assert {rows[k]["root"] for k in kids} == {one}
    fleet.edit(fleet.index(job), parent=two)
    rows = {r["verstr"]: r for r in _check(cache, fleet, fleet.snapshot())}
    assert {rows[k]["root"] for k in kids} == {two}
    assert rows[two]["root"] is None


def test_a_stuck_run_gets_a_signature_once_its_heartbeat_is_stale(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(2)
    verstr = fleet.append(state=running(T0))
    cache = LeaderboardCache()
    snap = fleet.snapshot()
    assert cache.page(snap, {}, limit=5)["rows"][0]["failure_sig"] is None
    _at(monkeypatch, T0 + datetime.timedelta(seconds=600))
    row = cache.page(snap, {}, limit=5)["rows"][0]
    assert row["verstr"] == verstr and row["failure_sig"].startswith("stuck")


def test_core_annotation_carries_root():
    rows = annotate_rows([{"verstr": "a"}, {"verstr": "b", "parent": "a"},
                          {"verstr": "c", "parent": "b"}], {})
    assert [r["root"] for r in rows] == [None, "a", "a"]
