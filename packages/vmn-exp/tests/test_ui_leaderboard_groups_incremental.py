"""Plan 22 K2: a grouping moved on across index generations (and time
buckets while runs are live) answers exactly what a cache that never saw an
earlier generation answers — and is not rebuilt from every row each time."""
import datetime
import random

import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui import leaderboard_groups as groups_mod

VOLATILE = ("stale_sec", "duration_sec")
SCHEMA = {"loss": {"goal": "min"}}
CASES = [
    dict(group="parent"), dict(group="parent", sort="loss"),
    dict(group="parent", sort="loss", agg="median", order="desc"),
    dict(group="branch", sort="acc", agg="max"), dict(group="status"),
    dict(group="params.opt", sort="timestamp"), dict(group="code_verstr", sort="loss"),
    dict(group="parent", query="metrics.loss < 0.6"),
    dict(group="parent", status="running,stuck", agg="best", sort="loss"),
    dict(group="branch", archived=True, sort="loss", agg="min"),
    dict(group="rerun_of", sort="loss"), dict(group="rerun_of", sort="loss", agg="best"),
    dict(group="rerun_of", status="running", sort="acc", agg="max"),
    dict(group="rerun_of", query="metrics.loss < 0.6", agg="median", sort="loss"),
    dict(group="forked_from"), dict(group="forked_from", sort="loss", agg="min"),
    dict(group="forked_from", status="succeeded,failed", archived=True, sort="loss"),
    dict(group="parent", sort="c:total"), dict(group="parent", sort="c:running", order="asc"),
    dict(group="status", sort="c:failed", order="desc"),
    dict(group="rerun_of", sort="c:done", agg="best"),
    dict(group="branch", sort="c:waiting", query="metrics.loss < 0.6"),
]


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(x) for k, x in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(x) for x in value]
    return value


class _Builds:
    """Counts groupings built from every row while :attr:`on`."""

    def __init__(self, monkeypatch):
        self.calls, self.on = 0, False
        real = groups_mod.Grouping.build

        def counted(*args, **kwargs):
            self.calls += self.on
            return real(*args, **kwargs)

        monkeypatch.setattr(groups_mod.Grouping, "build", staticmethod(counted))


def _answers(cache, snap):
    return [_strip(cache.groups(snap, SCHEMA, rows_per_group=100, limit=1000, **case))
            for case in CASES]


def _assert_same(cache, snap, builds=None):
    if builds:
        builds.on = True
    got = _answers(cache, snap)
    if builds:
        builds.on = False
    want = _answers(lb.LeaderboardCache(bucket_sec=cache.bucket_sec), snap)
    for case, mine, theirs in zip(CASES, got, want):
        assert mine == theirs, case


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("clock", ["frozen", "moving"])
def test_moved_groupings_equal_a_fresh_cache(monkeypatch, seed, clock):
    rng = random.Random(seed)
    now = T0
    _at(monkeypatch, now)
    fleet = Fleet(seed, links=True)
    fleet.seed(rng.randrange(150, 300), now)
    builds = _Builds(monkeypatch)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    for _ in range(8):
        if clock == "moving":
            now += datetime.timedelta(seconds=rng.choice([1, 7, 25, 61]))
            _at(monkeypatch, now)
        fleet.mutate(now, rng.randrange(1, 5))
        _assert_same(cache, fleet.snapshot(), builds)
        if clock == "moving":
            now += datetime.timedelta(seconds=rng.choice([3, 45]))
            _at(monkeypatch, now)
            _assert_same(cache, fleet.snapshot(), builds)
    # About once per case; every later generation and bucket moved it on
    # (16 answers per case: rebuilding each would count 160).
    assert builds.calls <= 2 * len(CASES)


def test_live_runs_under_one_sweep_move_between_status_groups(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(3)
    roots = fleet.seed(200, T0, sweeps=2, live=30)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    rng = random.Random(3)
    _assert_same(cache, fleet.snapshot())
    for step in range(1, 5):
        now = T0 + datetime.timedelta(seconds=20 * step)
        _at(monkeypatch, now)
        for _ in range(5):
            fleet.append(parent=rng.choice(roots), state=running(now, rng.choice([0, 70])))
        fleet.set_state(rng.randrange(len(fleet.specs)), finished(1))
        snap = fleet.snapshot()
        _assert_same(cache, snap)
        _at(monkeypatch, now + datetime.timedelta(seconds=65))
        _assert_same(cache, snap)


def test_a_large_delta_still_matches(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(5)
    fleet.seed(120, T0)
    cache = lb.LeaderboardCache(bucket_sec=2, size=256)
    _assert_same(cache, fleet.snapshot())
    fleet.remove(3)  # every later row moves
    _assert_same(cache, fleet.snapshot())
