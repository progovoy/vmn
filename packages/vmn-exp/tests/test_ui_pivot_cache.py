"""Plan 28 N2: pivots are memoized per index snapshot, and a settled outer
run's pivot (nothing live under it) is kept across generations until its
subtree changes, so a finished launch's heatmap is built once."""
import pytest
from leaderboard_group_rows import run, snapshot, v
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui import pivot_cache as pivot_cache_mod
from vmn_exp.ui.pivot import pivot_spec
from vmn_exp.ui.pivot_cache import PivotCache

SCHEMA = {}
SPEC = pivot_spec(rows="tags.date", cols="tags.group", scope=v(1))


def _specs(launch_state="ok", trial_state="ok"):
    out = [run(1, state=launch_state)]
    for n in range(2, 20):
        out.append(run(n, state=trial_state, parent=1,
                       tags={"date": f"d{n % 3}", "group": f"g{n % 2}"}))
    out += [run(n) for n in range(20, 40)]  # outside the launch
    return out


def _next(snap, replace=None, extra=(), generation=None):
    """*snap*'s next generation: its row objects kept but *replace*
    ``{verstr: row}``, *extra* rows appended (the index's identity contract)."""
    replace = replace or {}
    rows = [replace.get(row["verstr"], row) for row in snap.rows] + list(extra)
    states = dict(snap.run_states)
    for row in extra:
        states[row["verstr"]] = states.get(row["verstr"])
    return IndexSnapshot.build(snap.app_name, generation or snap.generation + 1, rows, states)


@pytest.fixture
def builds(monkeypatch):
    calls = []
    real = pivot_cache_mod.build_pivot

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(pivot_cache_mod, "build_pivot", counted)
    return calls


def _outside_row(snap, n):
    """A changed copy of the row of run *n* (outside the launch)."""
    row = snap.row(v(n))
    return {v(n): dict(row, note="edited")}


def test_one_snapshot_is_built_once(builds):
    snap = snapshot(_specs())
    pivots = PivotCache(lb.LeaderboardCache())
    first = pivots.pivot(snap, SCHEMA, SPEC)
    assert pivots.pivot(snap, SCHEMA, SPEC) is first
    assert len(builds) == 1


def test_a_settled_pivot_outlives_generations_outside_its_subtree(builds):
    snap = snapshot(_specs())
    pivots = PivotCache(lb.LeaderboardCache())
    first = pivots.pivot(snap, SCHEMA, SPEC)
    for generation in range(2, 6):
        snap = _next(snap, replace=_outside_row(snap, 20 + generation))
        assert pivots.pivot(snap, SCHEMA, SPEC) == first
    assert len(builds) == 1


def test_a_settled_pivot_is_built_again_once_its_subtree_changes(builds):
    snap = snapshot(_specs())
    pivots = PivotCache(lb.LeaderboardCache())
    pivots.pivot(snap, SCHEMA, SPEC)
    trial = snap.row(v(2))
    snap = _next(snap, replace={v(2): dict(trial, tags={"date": "d9", "group": "g0"})})
    body = pivots.pivot(snap, SCHEMA, SPEC)
    assert "d9" in [h["label"] for h in body["rows"]]
    assert len(builds) == 2


def test_a_new_run_under_the_launch_builds_it_again(builds):
    snap = snapshot(_specs())
    pivots = PivotCache(lb.LeaderboardCache())
    assert pivots.pivot(snap, SCHEMA, SPEC)["total"] == 18
    newcomer = snapshot([run(1), run(99, parent=1, tags={"date": "d0", "group": "g0"})]).rows[1]
    snap = _next(snap, extra=[newcomer])
    assert pivots.pivot(snap, SCHEMA, SPEC)["total"] == 19
    assert len(builds) == 2


def test_a_live_launch_is_built_per_generation(builds):
    snap = snapshot(_specs(launch_state="running"))
    pivots = PivotCache(lb.LeaderboardCache())
    pivots.pivot(snap, SCHEMA, SPEC)
    snap = _next(snap, replace=_outside_row(snap, 25))
    pivots.pivot(snap, SCHEMA, SPEC)
    assert len(builds) == 2


def test_other_arguments_are_other_pivots(builds):
    snap = snapshot(_specs())
    pivots = PivotCache(lb.LeaderboardCache())
    pivots.pivot(snap, SCHEMA, SPEC)
    other = pivot_spec(rows="tags.group", cols="tags.date", scope=v(1))
    body = pivots.pivot(snap, SCHEMA, other)
    assert [h["label"] for h in body["rows"]] == ["g0", "g1"]
    assert len(builds) == 2
