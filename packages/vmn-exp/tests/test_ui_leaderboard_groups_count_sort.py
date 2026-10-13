"""Plan 22 F10: ``sort=c:total|c:waiting|c:running|c:done|c:failed`` orders
the groups of the grouped board by that count (``failed`` counts stuck runs
too, as the inner-run count columns did); rows within a group, ties and the
no-value group keep the default order."""
import pytest
from leaderboard_group_rows import group_of, keys, members, run, snapshot, v
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_group_fields import NONE

SCHEMA = {"loss": {"goal": "min", "primary": True}}


def _groups(specs, group="parent", **params):
    return LeaderboardCache().groups(snapshot(specs, schema=SCHEMA), SCHEMA, group, **params)


def _sweep(parent, first, states, losses=None):
    losses = losses or [None] * len(states)
    return [run(first + i, parent=parent, state=state,
                metrics={} if loss is None else {"loss": loss})
            for i, (state, loss) in enumerate(zip(states, losses))]


# Sweep 1: 1 run; sweep 2: 3 runs; sweep 3: 2 runs; runs 1-3 and 4 have no
# parent, 4 is a loose row (1-3 head the sweeps).
FLEET = ([run(1), run(2), run(3), run(4)] + _sweep(1, 10, ["ok"])
         + _sweep(2, 20, ["ok", "fail", "stuck"]) + _sweep(3, 30, ["running", None]))


@pytest.mark.parametrize("order,want", [
    ("desc", [v(2), v(3), v(1), NONE]),
    ("asc", [v(1), v(3), v(2), NONE]),
    (None, [v(2), v(3), v(1), NONE]),  # most first, like the board's count headers
])
def test_groups_order_by_their_total(order, want):
    assert keys(_groups(FLEET, sort="c:total", order=order)) == want


@pytest.mark.parametrize("sort,want", [
    ("c:waiting", [v(3)]),
    ("c:running", [v(3)]),
    ("c:done", [v(1), v(2)]),
    ("c:failed", [v(2)]),  # one failed and one stuck run
])
def test_each_count_sorts_by_its_statuses(sort, want):
    assert keys(_groups(FLEET, sort=sort, order="desc"))[:len(want)] == want


def test_failed_counts_stuck_runs_too():
    specs = [run(1), run(2)] + _sweep(1, 10, ["stuck", "stuck"]) + _sweep(2, 20, ["fail", "ok"])
    assert keys(_groups(specs, sort="c:failed", order="desc")) == [v(1), v(2)]


def test_ties_keep_the_default_group_order():
    specs = ([run(1), run(2), run(3)] + _sweep(1, 10, ["ok", "ok"], [5.0, 5.0])
             + _sweep(2, 20, ["ok", "ok"], [1.0, 1.0]) + _sweep(3, 30, ["ok"], [3.0]))
    default = keys(_groups(specs))
    assert default == [v(2), v(3), v(1)]  # by mean loss
    assert keys(_groups(specs, sort="c:total", order="desc")) == [v(2), v(1), v(3)]
    assert keys(_groups(specs, sort="c:total", order="asc")) == [v(3), v(2), v(1)]


def test_rows_within_a_group_keep_the_default_order():
    specs = [run(1)] + _sweep(1, 10, ["ok", "ok", "ok"], [3.0, 1.0, 2.0])
    default = _groups(specs)
    for order in ("asc", "desc"):
        counted = _groups(specs, sort="c:done", order=order)
        assert members(group_of(counted, v(1))) == members(group_of(default, v(1)))
    assert members(group_of(default, v(1))) == [v(11), v(12), v(10)]


def test_the_no_value_group_stays_last_however_large():
    specs = [run(i) for i in range(1, 8)] + _sweep(1, 10, ["ok"])
    for order in ("asc", "desc"):
        assert keys(_groups(specs, sort="c:total", order=order)) == [v(1), NONE]


def test_counts_sort_field_groups_and_follow_the_filters():
    specs = ([run(1, branch="a"), run(2, branch="b", state="fail"), run(3, branch="b"),
              run(4, branch="b")])
    assert keys(_groups(specs, "branch", sort="c:total")) == ["b", "a"]
    assert keys(_groups(specs, "branch", sort="c:total", status="failed")) == ["b"]
    assert keys(_groups(specs, "branch", sort="c:done", order="asc")) == ["a", "b"]


def test_without_group_a_count_sort_is_an_unknown_sort():
    specs = [run(1, metrics={"loss": 2.0}), run(2, metrics={"loss": 1.0}), run(3)]
    cache, snap = LeaderboardCache(), snapshot(specs, schema=SCHEMA)
    for order in (None, "asc", "desc"):
        counted = cache.page(snap, SCHEMA, sort="c:total", order=order, limit=10)
        unknown = cache.page(snap, SCHEMA, sort="no_such_metric", order=order, limit=10)
        assert [r["verstr"] for r in counted["rows"]] == [r["verstr"] for r in unknown["rows"]]
