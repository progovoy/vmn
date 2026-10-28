"""Plan 28 B0 baselines at fgm's shape (:mod:`uiload.fgm_tree`): the app's
``experiments-status``, an outer run's summary (with and without
``?split=tags.kind``), the grouped board, a minute-keyed waiting count (what
P1's ``ago()`` rebuilds once a minute) and the split tallies' memory per
outer run, off an in-memory index snapshot. Timed, so serial; the budgets
are generous ceilings, the printed numbers are the baseline.

Runs ``fgm-small`` (~52k runs: two finished launches and a live one). The
full 588k-run shape (32 launches, ~10k running), ~30 s to build and ~10 GB:

    VMN_UILOAD_FGM_PROFILE=fgm python -m pytest -s -n0 -p no:cacheprovider \\
        packages/vmn-exp/tests/test_uiload_fgm_bench.py
"""
import datetime
import os
import statistics
import time
import tracemalloc

import pytest
from uiload import fgm_records, fgm_tree
from vmn_exp.core import status as status_mod
from vmn_exp.ui.job_views import JobViews
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

PROFILE = os.environ.get("VMN_UILOAD_FGM_PROFILE", "fgm-small")
NOW = 1_800_000_000.0
FINISHING = 50  # runs one refresh sees end
# Ceilings in seconds: (first request after a warm base, memoized again).
BUDGETS = {"fgm-small": {"status": 1.0, "summary": 2.0, "board": 3.0, "waiting": 2.0},
           "fgm": {"status": 10.0, "summary": 20.0, "board": 30.0, "waiting": 20.0}}
MEMOIZED_SEC = 0.05
SPLIT = "tags.kind"


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _ms(seconds):
    return f"{seconds * 1000:.1f} ms"


@pytest.fixture(scope="module")
def fleet():
    at = datetime.datetime.fromtimestamp(NOW, datetime.timezone.utc)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(status_mod, "_now", lambda now=None: now or at)
        built = time.perf_counter()
        snap, specs = fgm_records.snapshot(fgm_tree.get_profile(PROFILE), NOW)
        print(f"\n{PROFILE}: {len(snap.rows)} runs built in {time.perf_counter() - built:.1f}s")
        yield snap, specs, at


@pytest.fixture
def warmed(fleet):
    snap, specs, at = fleet
    cache = LeaderboardCache()
    print(f"\nboard base (the refresher's warm) {_ms(_timed(lambda: cache.warm(snap)))}")
    return cache, snap, specs, at


def _launches(specs):
    launches = [s for s in specs if s["tags"]["kind"] == "launch"]
    return (next(s["verstr"] for s in launches if s["fate"] == "running"),
            next(s["verstr"] for s in launches if s["fate"] == "succeeded"))


def _running(specs, n):
    return [s["verstr"] for s in specs if s["fate"] == "running" and s["level"] >= 3][:n]


def _budget(name):
    return BUDGETS.get(PROFILE, BUDGETS["fgm"])[name]


@pytest.mark.serial
def test_experiments_status(warmed):
    cache, snap, specs, at = warmed
    first = _timed(lambda: cache.status_summary(snap, at))
    again = _timed(lambda: cache.status_summary(snap, at))
    later = fgm_records.next_generation(snap, _running(specs, FINISHING), NOW)
    moved = _timed(lambda: cache.status_summary(later, at))
    body = cache.status_summary(later, at)
    print(f"experiments-status: first {_ms(first)}, again {_ms(again)}, next generation "
          f"{_ms(moved)}; counts {body['counts']}")
    assert body["total"] == len(snap.rows)
    assert first <= _budget("status") and again <= MEMOIZED_SEC and moved <= _budget("status")


@pytest.mark.serial
@pytest.mark.parametrize("split", [None, SPLIT])
def test_outer_run_summary(warmed, split):
    cache, snap, specs, at = warmed
    views, schema = JobViews(cache), snap.declared_schema()
    live, ended = _launches(specs)
    times = {}
    for name, launch in (("live", live), ("ended", ended)):
        times[name] = _timed(lambda launch=launch: views.summary(snap, schema, launch, split))
    again = _timed(lambda: views.summary(snap, schema, live, split))
    later = fgm_records.next_generation(snap, _running(specs, FINISHING), NOW)
    moved = _timed(lambda: views.summary(later, schema, live, split))
    body = views.summary(later, schema, live, split)
    print(f"summary split={split}: live launch {_ms(times['live'])}, ended launch "
          f"{_ms(times['ended'])}, again {_ms(again)}, next generation {_ms(moved)}; "
          f"{body['total']} runs, declared {body['declared_progress']}")
    assert body["declared_progress"]["unit"] == "dates"
    assert (body["by"] is not None) == bool(split)
    assert max(times.values()) <= _budget("summary") and again <= MEMOIZED_SEC
    assert moved <= _budget("summary")


BOARDS = {
    "launch by tags.kind": lambda live, ended: dict(group="tags.kind", scope=live),
    "ended launch by trade_date, unstable": lambda live, ended: dict(
        group="tags.trade_date", scope=ended, query='tags.health = "unstable"'),
    "app by parent, on value": lambda live, ended: dict(group="parent", sort="value"),
}


@pytest.mark.serial
@pytest.mark.parametrize("board", sorted(BOARDS))
def test_grouped_board(warmed, board):
    cache, snap, specs, at = warmed
    params, schema = BOARDS[board](*_launches(specs)), snap.declared_schema()
    grouped = lambda: cache.groups(snap, schema, limit=50, **params)  # noqa: E731
    first = _timed(grouped)
    again = statistics.median(_timed(grouped) for _ in range(5))
    body = grouped()
    print(f"grouped board {board}: first {_ms(first)}, again {_ms(again)}; "
          f"{body['total_groups']} groups, {body['total_rows']} rows")
    assert body["total_groups"] > 0
    assert first <= _budget("board") and again <= MEMOIZED_SEC


@pytest.mark.serial
def test_a_minute_keyed_waiting_count(warmed):
    """P1's ``status = "created" and timestamp < ago("1h")`` is rebuilt once a
    minute: each minute's literal is a fresh filtered order."""
    cache, snap, specs, at = warmed
    schema = snap.declared_schema()
    times, totals = [], []
    for minute in range(3):
        since = fgm_records.iso(NOW - 3600 + 60 * minute)
        query = f'status = "created" and timestamp < "{since}"'
        times.append(_timed(lambda q=query: totals.append(
            cache.page(snap, schema, query=q, limit=1)["total"])))
    plain = _timed(lambda: cache.page(snap, schema, query='tags.health = "unstable"', limit=1))
    print(f"minute-keyed waiting count: {[_ms(t) for t in times]} ({totals[0]} runs); "
          f"a time-free query's first build {_ms(plain)}")
    assert totals[0] > 0
    assert max(times) <= _budget("waiting")


@pytest.mark.serial
def test_split_tallies_memory_per_outer_run(warmed):
    """P3: the split rollups' memory over the plain ones, per run with children."""
    cache, snap, specs, at = warmed
    views, schema = JobViews(cache), snap.declared_schema()
    live, _ = _launches(specs)
    views.summary(snap, schema, live)
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        views.summary(snap, schema, live, SPLIT)
        grown = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    parents = len({s["parent"] for s in specs if s["parent"]})
    print(f"split={SPLIT} tallies: {grown / 1024:.0f} KB over {parents} runs with children, "
          f"{grown / parents:.0f} B each")
    assert grown / parents <= 64 * 1024
