"""The app status summary (``experiments-status``, ``apps-status``) is carried
from one index generation to the next by the row delta, not recounted over
every row: it must equal :func:`status_summary` over the board's rows at
every generation and every time bucket — live runs going stuck, an outer
run ending (its subtree settling), archiving, removal, recent failures."""
import datetime

import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.status_summary import status_summary

from vmn_exp.core import status as status_mod


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _brute(snap, now):
    return status_summary(LeaderboardCache().rows(snap), now)


def _check(cache, snap, now):
    assert cache.status_summary(snap, now) == _brute(snap, now)


def _churn(fleet, roots, now):
    """One refresh's changes: the fleet's random ones plus failures with a
    finish time (recent or not), outers ending or restarting, archiving."""
    rng = fleet.rng
    fleet.mutate(now, rng.choice([1, 4, 12]))
    n = len(fleet.specs)
    for i in rng.sample(range(n), 2):
        fleet.set_state(i, fleet.ended(now - datetime.timedelta(
            seconds=rng.choice([0, 3600, 86000, 90000])), code=rng.choice([0, 1])))
    for root in rng.sample(roots, 2):
        if any(s["verstr"] == root for s in fleet.specs):
            fleet.set_state(fleet.index(root), rng.choice(
                [finished(0), finished(1), running(now), running(now, age=600), None]))
    i = rng.randrange(n)
    fleet.edit(i, archived=not fleet.specs[i]["archived"])


@pytest.mark.parametrize("seed", range(6))
def test_carried_counts_equal_a_full_recount_every_generation(monkeypatch, seed):
    fleet = Fleet(seed)
    roots = fleet.seed(300, T0, sweeps=6, live=12)
    for root in roots:  # nested outers, some never started
        kid = fleet.append(parent=root)
        fleet.append(parent=kid)
    cache, now = LeaderboardCache(), T0
    for _ in range(25):
        _at(monkeypatch, now)
        snap = fleet.snapshot()
        _check(cache, snap, now)
        for step in sorted(fleet.rng.sample([3, 70, 600, 86400], 2)):  # later buckets
            now += datetime.timedelta(seconds=step)
            _at(monkeypatch, now)
            _check(cache, snap, now)
        now += datetime.timedelta(seconds=fleet.rng.choice([1, 3, 70, 3600]))
        _at(monkeypatch, now)
        _churn(fleet, roots, now)


def test_an_outer_that_ends_moves_its_subtree_to_settled(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(7)
    for _ in range(200):
        fleet.append(state=finished(0))
    outer = fleet.append(state=running(T0))
    for state in (None, None, running(T0, age=600), finished(1)):
        fleet.append(parent=outer, state=state)
    cache = LeaderboardCache()
    before = cache.status_summary(fleet.snapshot(), T0)
    assert (before["never_started"], before["lost"]) == (0, 0)
    fleet.set_state(fleet.index(outer), finished(0))
    snap = fleet.snapshot()
    after = cache.status_summary(snap, T0)
    assert (after["never_started"], after["lost"]) == (2, 1)
    assert after == _brute(snap, T0)


def test_a_live_run_goes_stuck_within_one_snapshot(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(8)
    for _ in range(200):
        fleet.append(state=finished(0))
    fleet.append(state=running(T0))
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert cache.status_summary(snap, T0)["rollup"] == "running"
    later = T0 + datetime.timedelta(seconds=600)
    _at(monkeypatch, later)
    body = cache.status_summary(snap, later)
    assert (body["rollup"], body["counts"]["stuck"]) == ("stuck", 1)
    assert body == _brute(snap, later)


def test_a_recent_failure_ages_out_of_the_window(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(9)
    for _ in range(50):
        fleet.append(state=finished(0))
    fleet.append(state=fleet.ended(T0, code=1))
    cache, snap = LeaderboardCache(), fleet.snapshot()
    assert cache.status_summary(snap, T0)["failed_recent"] == 1
    later = T0 + datetime.timedelta(days=2)
    _at(monkeypatch, later)
    assert cache.status_summary(snap, later)["failed_recent"] == 0
