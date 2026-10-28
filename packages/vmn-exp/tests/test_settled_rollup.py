"""The board's rollups settle what an ended outer run left behind: its
never-started descendants count as ``never_started`` and its stuck ones as
``lost`` beside the status ``counts`` (never in them), in the job rollup,
the run detail's fleet and the app's status summary — derived per index
generation, moved by the generation's deltas (an outer that ends re-settles
its subtree once), and equal to a from-scratch build."""
import datetime

import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.job_rollup_payload import job_payload
from vmn_exp.ui.job_tally import RollupSpec, Tally
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache, _Base
from vmn_exp.ui.status_summary import status_summary

from vmn_exp.core import status as status_mod

NEVER, LOST = "never_started", "lost"
SPEC = RollupSpec({})


def _at(monkeypatch, when):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or when)


def _stale():
    return running(T0, age=600)


def _row(n, status, settled=None):
    return {"verstr": f"v{n}", "parent": "job", "status": status, "settled": settled,
            "metrics": {}}


class TestPayload:
    ROWS = [_row(0, "succeeded"), _row(1, "failed"), _row(2, "created", NEVER),
            _row(3, "created", NEVER), _row(4, "stuck", LOST)]

    def _payload(self, status, rows=ROWS, **job):
        return job_payload(dict({"verstr": "job", "status": status}, **job),
                           [Tally.of(rows, SPEC)], SPEC, T0)

    def test_settled_runs_count_beside_the_counts(self):
        p = self._payload("succeeded")
        assert p["counts"] == {"running": 0, "waiting": 0, "succeeded": 1, "failed": 1,
                               "stuck": 0}
        assert (p[NEVER], p[LOST], p["total"]) == (2, 1, 5)
        assert p["done"] == 3  # a lost run has finished, badly
        assert p["failed_pct"] == 40.0

    def test_an_ended_job_has_nothing_left(self):
        p = self._payload("succeeded", sweep_planned=10)
        assert p["ended"] is True and p["eta_sec"] == 0
        assert p["expected"] == 10

    def test_an_open_job_has_not_ended(self):
        rows = [_row(0, "succeeded"), _row(1, "created")]
        p = self._payload("running", rows)
        assert p["ended"] is False and p["counts"]["waiting"] == 1 and p[NEVER] == 0


def test_the_status_summary_counts_settled_runs_apart():
    rows = [{"status": "stuck", "settled": LOST}, {"status": "created", "settled": NEVER},
            {"status": "succeeded"}]
    body = status_summary(rows, T0)
    assert body["counts"]["stuck"] == 0 and body["counts"]["created"] == 0
    assert (body[NEVER], body[LOST], body["total"]) == (1, 1, 3)
    assert body["rollup"] is None  # nothing lost needs a look: its outer ended


def _fleet(seed):
    """A fleet big enough that one generation's few changes are a delta."""
    fleet = Fleet(seed)
    for _ in range(100):
        fleet.append(state=finished(0))
    return fleet


def _count_builds(monkeypatch):
    builds = []
    real = _Base.build
    monkeypatch.setattr(_Base, "build", classmethod(lambda cls, *a: builds.append(1) or real(*a)))
    return builds


def _job(fleet, outer_state, kid_states):
    outer = fleet.append(state=outer_state)
    return outer, [fleet.append(parent=outer, state=s) for s in kid_states]


def _rows(cache, snap):
    return {r["verstr"]: (r["status"], r.get("settled"), r["tree_status"])
            for r in cache.rows(snap, archived=True)}


def _same_as_a_fresh_build(cache, snap, outers):
    fresh = LeaderboardCache()
    assert _rows(cache, snap) == _rows(fresh, snap)
    for outer in outers:
        got, want = cache.job_rollup(snap, {}, outer), fresh.job_rollup(snap, {}, outer)
        for key in ("counts", "total", "done", NEVER, LOST, "ended"):
            assert got[key] == want[key], key


def test_an_outer_that_ends_settles_its_children_once(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _fleet(1)
    outer, kids = _job(fleet, running(T0), [None, None, None, _stale(), finished(0), finished(1)])
    cache = LeaderboardCache()
    rollup = cache.job_rollup(fleet.snapshot(), {}, outer)
    assert (rollup["counts"]["waiting"], rollup["counts"]["stuck"], rollup[NEVER]) == (3, 1, 0)
    builds = _count_builds(monkeypatch)

    fleet.set_state(fleet.index(outer), finished(0))
    snap = fleet.snapshot()
    rollup = cache.job_rollup(snap, {}, outer)
    assert builds == []  # derived from the last generation
    assert (rollup["counts"]["waiting"], rollup["counts"]["stuck"]) == (0, 0)
    assert (rollup[NEVER], rollup[LOST], rollup["done"], rollup["ended"]) == (3, 1, 3, True)
    rows = _rows(cache, snap)
    assert rows[outer][2] == "failed"  # the lost run
    assert [rows[k][1] for k in kids] == [NEVER, NEVER, NEVER, LOST, None, None]
    _same_as_a_fresh_build(cache, snap, [outer])

    fleet.set_state(fleet.index(kids[0]), running(T0))  # a settled child starts after all
    snap = fleet.snapshot()
    rollup = cache.job_rollup(snap, {}, outer)
    assert builds == [1]  # the fresh build above only
    assert (rollup[NEVER], rollup["counts"]["running"]) == (2, 1)
    assert _rows(cache, snap)[kids[0]][1] == "outlived"
    _same_as_a_fresh_build(cache, snap, [outer])


def test_a_never_started_container_passes_the_settlement_down(monkeypatch):
    _at(monkeypatch, T0)
    fleet = _fleet(2)
    top = fleet.append(state=running(T0))
    mid = fleet.append(parent=top)
    leaves = [fleet.append(parent=mid) for _ in range(3)]
    cache = LeaderboardCache()
    assert cache.job_rollup(fleet.snapshot(), {}, top)["counts"]["waiting"] == 4
    builds = _count_builds(monkeypatch)
    fleet.set_state(fleet.index(top), finished(0))
    snap = fleet.snapshot()
    assert cache.job_rollup(snap, {}, top)[NEVER] == 4
    assert builds == []
    assert cache.job_rollup(snap, {}, mid)["ended"] is True
    assert {_rows(cache, snap)[v][1] for v in leaves} == {NEVER}
    _same_as_a_fresh_build(cache, snap, [top, mid])


def test_a_live_child_of_an_ended_outer_turns_lost_between_buckets(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(3)
    outer, (live, _) = _job(fleet, finished(0), [running(T0), None])
    cache, snap = LeaderboardCache(), fleet.snapshot()
    rollup = cache.job_rollup(snap, {}, outer)
    assert (rollup["counts"]["running"], rollup[NEVER], rollup[LOST]) == (1, 1, 0)
    _at(monkeypatch, T0 + datetime.timedelta(seconds=600))
    rollup = cache.job_rollup(snap, {}, outer)
    assert (rollup["counts"]["running"], rollup["counts"]["stuck"], rollup[LOST]) == (0, 0, 1)
    rows = _rows(cache, snap)
    assert rows[live] == ("stuck", LOST, "failed") and rows[outer][2] == "failed"


def test_the_run_detail_fleet_counts_settled_runs_apart(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(4)
    outer, _ = _job(fleet, finished(0), [None, _stale(), finished(0)])
    cache, snap = LeaderboardCache(), fleet.snapshot()
    fleet_counts = JobViews(cache).detail_status(snap, {}, outer)["fleet"]
    assert (fleet_counts[NEVER], fleet_counts[LOST]) == (1, 1)
    assert fleet_counts["counts"]["created"] == 0 and fleet_counts["counts"]["stuck"] == 0


@pytest.mark.parametrize("seed", range(4))
def test_random_generations_match_a_fresh_build(monkeypatch, seed):
    fleet = Fleet(seed)
    roots = fleet.seed(200, T0, sweeps=5, live=8)
    for root in roots:  # nested outers, some never started
        fleet.append(parent=root)
    cache, now = LeaderboardCache(), T0
    for _ in range(10):
        _at(monkeypatch, now)
        snap = fleet.snapshot()
        outers = [r["verstr"] for r in cache.rows(snap, archived=True) if r["children"]]
        _same_as_a_fresh_build(cache, snap, outers)
        assert status_summary(cache.rows(snap), now) == status_summary(
            LeaderboardCache().rows(snap), now)
        now += datetime.timedelta(seconds=fleet.rng.choice([0, 3, 70]))
        _at(monkeypatch, now)  # a later bucket: live outer runs may go stuck
        _same_as_a_fresh_build(cache, snap, outers)
        fleet.mutate(now, fleet.rng.choice([1, 4, 12]))
        for root in fleet.rng.sample(roots, 2):  # outers end and start again
            if any(s["verstr"] == root for s in fleet.specs):
                fleet.set_state(fleet.index(root), fleet.rng.choice(
                    [finished(0), finished(1), running(now), _stale(), None]))


def test_a_grouped_board_counts_lost_runs_failed_and_never_started_ones_in_the_total(monkeypatch):
    _at(monkeypatch, T0)
    fleet = Fleet(5)
    outer, _ = _job(fleet, finished(0), [None, None, _stale(), finished(0)])
    groups = LeaderboardCache().groups(fleet.snapshot(), {}, group="parent")["groups"]
    (group,) = [g for g in groups if g["key"] == outer]
    assert group["counts"] == {"total": 4, "running": 0, "waiting": 0, "done": 1, "failed": 1,
                               "stuck": 0}
