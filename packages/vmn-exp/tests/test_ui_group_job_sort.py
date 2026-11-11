"""A grouped Outer runs board (``top`` with ``group``) takes a ``job:*`` sort:
each group's attempts order by it, and the groups by their first attempt
under it (``job:started``: a group by its latest attempt's start). With
``collapse_all`` the headers alone keep that order. Without ``top`` a job
sort stays refused."""
import pytest
from leaderboard_group_rows import keys, members, run, snapshot, v
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

SCHEMA = {"loss": {"goal": "min", "primary": True}}


def _attempt(n, children, launch, state="ok"):
    return [run(n, state=state, tags={"launch_id": launch})] + [
        run(n + 1 + i, state=state, parent=n, metrics={"loss": 1.0}) for i in range(children)]


def _groups(specs, sort, order=None, top="jobs", **extra):
    return LeaderboardCache().groups(snapshot(specs), SCHEMA, "tags.launch_id", sort=sort,
                                     order=order, top=top, **extra)


# L2: 300, created first (so first by default), started an hour ago;
# L1: 100 started an hour ago, 200 now.
STARTED = (_attempt(300, 1, "L2", "stuck") + _attempt(100, 1, "L1", "stuck")
           + _attempt(200, 1, "L1"))


def test_groups_order_by_their_latest_attempts_start():
    assert keys(_groups(STARTED, None)) == ["L2", "L1"]
    payload = _groups(STARTED, "job:started")
    assert keys(payload) == ["L1", "L2"]
    assert members(payload["groups"][0]) == [v(200), v(100)]


def test_one_row_per_group_keeps_the_job_order():
    payload = _groups(STARTED, "job:started", rows_per_group=0)
    assert keys(payload) == ["L1", "L2"]
    assert all(g["rows"] == [] for g in payload["groups"])


# L1: 100 with 3 runs below, 200 with 1; L2: 300 with 5.
TOTALS = _attempt(100, 3, "L1") + _attempt(200, 1, "L1") + _attempt(300, 5, "L2")


@pytest.mark.parametrize("order, groups, l1", [
    (None, ["L2", "L1"], [v(100), v(200)]),
    ("asc", ["L1", "L2"], [v(200), v(100)]),
])
def test_a_job_sort_orders_attempts_and_groups(order, groups, l1):
    payload = _groups(TOTALS, "job:total", order)
    assert keys(payload) == groups
    assert members(next(g for g in payload["groups"] if g["key"] == "L1")) == l1


def test_a_grouped_job_sort_still_needs_top():
    with pytest.raises(ValueError, match="needs top=1"):
        _groups(TOTALS, "job:total", top=False)


def test_a_job_sort_keeps_the_query():
    payload = _groups(STARTED, "job:started", query='tags.launch_id = "L1"')
    assert keys(payload) == ["L1"] and payload["total_rows"] == 2
