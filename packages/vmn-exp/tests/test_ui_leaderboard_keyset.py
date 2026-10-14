"""Plan 23 S6: keyset paging. A page asked for with the previous page's
``next_cursor`` starts strictly after that page's last row in the current
order, so paging a whole list while the fleet changes yields every row that
did not move exactly once (a row that moved past the cursor may come again:
the client keeps the first)."""
import datetime
import random

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.leaderboard_jobs import JOB_SORTS

from vmn_exp.core import status as status_mod

SCHEMAS = [{}, {"loss": {"goal": "min", "primary": True}}]
CASES = [
    dict(), dict(sort="loss"), dict(sort="loss", order="desc"), dict(sort="acc", order="asc"),
    dict(sort="timestamp"), dict(sort="started_at", order="asc"), dict(sort="idx"),
    dict(status="succeeded,created"), dict(query="metrics.loss < 0.6", sort="loss"),
    dict(top=True), dict(top=True, sort="job:total"), dict(top=True, sort="job:progress"),
    dict(top=True, sort="job:started", order="asc"), dict(last=60, sort="loss"),
    dict(archived=True, sort="acc"), dict(scope=0, sort="loss"), dict(scope=1),
    dict(top=True, match_subtree=True, query='status = "failed"'),
]
DATES = ("timestamp", "started_at", "finished_at")


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _sort_data(row, sort):
    job = (row.get("job") or {}).get(JOB_SORTS.get(sort)) if sort in JOB_SORTS else None
    return (repr(sorted(row["metrics"].items())), tuple(row.get(d) for d in DATES), job)


def _order(cache, snap, schema, params):
    return cache.page(snap, schema, limit=10**6, **params)["rows"]


def _unmoved(orders, sort):
    """Rows in every order with the same sort data and the same predecessors."""
    common = set.intersection(*({r["verstr"] for r in rows} for rows in orders))
    data = {}
    moved = set()
    for rows in orders:
        seen = set()
        for row in rows:
            v = row["verstr"]
            if v not in common:
                continue
            got = (_sort_data(row, sort), frozenset(seen))
            if data.setdefault(v, got) != got:
                moved.add(v)
            seen.add(v)
    return common - moved


def _page_through(seed, schema, params, limit=7):
    fleet, rng = Fleet(seed), random.Random(seed)
    jobs = fleet.seed_jobs(4, 15, T0, live=6)
    fleet.seed(40, T0, sweeps=2, live=4)
    if "scope" in params:
        params = dict(params, scope=jobs[params["scope"]])
    cache = LeaderboardCache()
    now, got, orders = T0, [], []
    snap = fleet.snapshot()
    cursor = None
    for _ in range(200):
        orders.append(_order(cache, snap, schema, params))
        page = cache.page(snap, schema, limit=limit, cursor=cursor, **params)
        got += [row["verstr"] for row in page["rows"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
        now += datetime.timedelta(seconds=rng.choice([0, 1, 3]))
        fleet.mutate(now, rng.randrange(4))
        snap = fleet.snapshot()
    else:
        pytest.fail("paging never ended")
    orders.append(_order(cache, snap, schema, params))
    return got, orders


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("case", range(len(CASES)))
def test_paging_by_cursor_while_mutating_yields_each_unmoved_row_once(seed, case):
    params = CASES[case]
    schema = SCHEMAS[seed % 2]
    got, orders = _page_through(seed * 31 + case, schema, params)
    unmoved = _unmoved(orders, params.get("sort"))
    twice = {v for v in got if got.count(v) > 1}
    assert not twice & unmoved, "an unmoved row came twice"
    assert not unmoved - set(got)


def test_without_changes_cursor_paging_equals_the_full_order():
    fleet = Fleet(3)
    jobs = fleet.seed(80, T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    for schema in SCHEMAS:
        for params in CASES:
            if "scope" in params:
                params = dict(params, scope=jobs[params["scope"]])
            want = [r["verstr"] for r in _order(cache, snap, schema, params)]
            got, cursor = [], None
            while True:
                page = cache.page(snap, schema, limit=9, cursor=cursor, **params)
                got += [r["verstr"] for r in page["rows"]]
                assert page["total"] == len(want)
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert got == want, params


def test_an_offset_page_carries_a_next_cursor_and_the_last_page_none():
    fleet = Fleet(4)
    fleet.seed(30, T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    first = cache.page(snap, {}, limit=10, sort="loss")
    rest = cache.page(snap, {}, limit=10, sort="loss", cursor=first["next_cursor"])
    assert rest["rows"] == cache.page(snap, {}, limit=10, offset=10, sort="loss")["rows"]
    assert cache.page(snap, {}, limit=50, sort="loss")["next_cursor"] is None


def test_a_cursor_from_another_sort_or_filter_is_refused():
    fleet = Fleet(5)
    fleet.seed(30, T0)
    cache, snap = LeaderboardCache(), fleet.snapshot()
    cursor = cache.page(snap, {}, limit=5, sort="loss")["next_cursor"]
    for other in (dict(sort="acc"), dict(sort="loss", order="asc"),
                  dict(sort="loss", status="running"), dict(sort="loss", query="idx > 1"),
                  dict(sort="loss", top=True)):
        with pytest.raises(ValueError):
            cache.page(snap, {}, limit=5, cursor=cursor, **other)
    for junk in ("x", "eyJ9", ""):
        with pytest.raises(ValueError):
            cache.page(snap, {}, limit=5, cursor=junk + "!", sort="loss")


def test_a_gone_cursor_row_resumes_after_the_page_rows_still_there():
    fleet = Fleet(6)
    fleet.seed(30, T0, live=0)
    cache = LeaderboardCache()
    page = cache.page(fleet.snapshot(), {}, limit=10)
    seen = [r["verstr"] for r in page["rows"]]
    fleet.remove(fleet.index(seen[-1]))
    rest = cache.page(fleet.snapshot(), {}, limit=100, cursor=page["next_cursor"])
    got = [r["verstr"] for r in rest["rows"]]
    assert not set(got) & set(seen)
    assert len(seen) - 1 + len(got) == 29
