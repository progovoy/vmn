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
import os
import statistics
import time
import tracemalloc

import pytest
from bench_timing import fastest_each
from uiload import fgm_records, fgm_tree
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


class Fleet:
    """The snapshot and the few planned facts the benches read (not the specs)."""

    def __init__(self, snap, specs):
        self.snap, self.schema = snap, snap.declared_schema()
        self.live, self.ended = fgm_tree.launches(specs)
        finishing = [s["verstr"] for s in specs if s["fate"] == "running" and s["level"] >= 3]
        self.later = fgm_records.next_generation(snap, finishing[:FINISHING], NOW)
        self.parents = len({s["parent"] for s in specs if s["parent"]})


@pytest.fixture(scope="module")
def fleet():
    at = fgm_records.frozen_now(NOW)
    built = time.perf_counter()
    fleet = Fleet(*fgm_records.snapshot(fgm_tree.get_profile(PROFILE), NOW))
    print(f"\n{PROFILE}: {len(fleet.snap.rows)} runs built in {time.perf_counter() - built:.1f}s")
    yield fleet, at


def _warm(cache, snap):
    print(f"\nboard base (the refresher's warm) {_ms(_timed(lambda: cache.warm(snap)))}")
    return cache


@pytest.fixture(scope="module")
def board(fleet):
    return _warm(LeaderboardCache(now=lambda: fleet[1]), fleet[0].snap)


@pytest.fixture
def warmed(fleet, board):
    """The shared board, warm on the first generation again (a bench before
    may have moved it on); each bench reads keys of its own."""
    fleet, at = fleet
    board.warm(fleet.snap)
    return board, fleet, at


def _budget(name):
    return BUDGETS.get(PROFILE, BUDGETS["fgm"])[name]


def _boards(warmed):
    """The warmed shared board, then fresh ones warm on the first generation."""
    cache, fleet, at = warmed
    yield cache
    while True:
        fresh = LeaderboardCache(now=lambda: at)
        fresh.warm(fleet.snap)
        yield fresh


def _fastest(warmed, steps, budgets):
    """``(fastest seconds of each step, what the last pass kept)`` over passes
    of *steps(board)* (``({step: seconds}, kept)``), each on a board none of
    whose keys an earlier pass read."""
    boards, kept = _boards(warmed), []

    def attempt():
        took, keep = steps(next(boards))
        kept.append(keep)
        return took

    return fastest_each(attempt, budgets), kept[-1]


@pytest.mark.serial
def test_experiments_status(warmed):
    _, fleet, at = warmed
    snap, later = fleet.snap, fleet.later
    took, cache = _fastest(warmed, lambda cache: ({
        "first": _timed(lambda: cache.status_summary(snap, at)),
        "again": _timed(lambda: cache.status_summary(snap, at)),
        "moved": _timed(lambda: cache.status_summary(later, at))}, cache),
        {"first": _budget("status"), "again": MEMOIZED_SEC, "moved": _budget("status")})
    body = cache.status_summary(later, at)
    print(f"experiments-status: first {_ms(took['first'])}, again {_ms(took['again'])}, "
          f"next generation {_ms(took['moved'])}; counts {body['counts']}")
    assert body["total"] == len(snap.rows)
    assert took["first"] <= _budget("status") and took["again"] <= MEMOIZED_SEC
    assert took["moved"] <= _budget("status")


def _summaries(cache, fleet, split):
    views, snap, schema, live = JobViews(cache), fleet.snap, fleet.schema, fleet.live
    times = {}
    for name, launch in (("live", live), ("ended", fleet.ended)):
        times[name] = _timed(lambda launch=launch: views.summary(snap, schema, launch, split))
    times["again"] = _timed(lambda: views.summary(snap, schema, live, split))
    times["moved"] = _timed(lambda: views.summary(fleet.later, schema, live, split))
    return times, views


@pytest.mark.serial
@pytest.mark.parametrize("split", [None, SPLIT])
def test_outer_run_summary(warmed, split):
    _, fleet, _ = warmed
    summary = _budget("summary")
    times, views = _fastest(warmed, lambda cache: _summaries(cache, fleet, split), {
        "live": summary, "ended": summary, "again": MEMOIZED_SEC, "moved": summary})
    body = views.summary(fleet.later, fleet.schema, fleet.live, split)
    print(f"summary split={split}: live launch {_ms(times['live'])}, ended launch "
          f"{_ms(times['ended'])}, again {_ms(times['again'])}, next generation "
          f"{_ms(times['moved'])}; {body['total']} runs, declared {body['declared_progress']}")
    assert body["declared_progress"]["unit"] == "dates"
    assert (body["by"] is not None) == bool(split)
    assert max(times["live"], times["ended"]) <= summary and times["again"] <= MEMOIZED_SEC
    assert times["moved"] <= summary


BOARDS = {
    "launch by tags.kind": lambda live, ended: dict(group="tags.kind", scope=live),
    "ended launch by trade_date, unstable": lambda live, ended: dict(
        group="tags.trade_date", scope=ended, query='tags.health = "unstable"'),
    "app by parent, on value": lambda live, ended: dict(group="parent", sort="value"),
}


@pytest.mark.serial
@pytest.mark.parametrize("shape", sorted(BOARDS))
def test_grouped_board(warmed, shape):
    _, fleet, _ = warmed
    params = BOARDS[shape](fleet.live, fleet.ended)

    def steps(cache):
        grouped = lambda: cache.groups(fleet.snap, fleet.schema, limit=50, **params)  # noqa: E731
        return {"first": _timed(grouped),
                "again": statistics.median(_timed(grouped) for _ in range(5))}, grouped

    took, grouped = _fastest(warmed, steps, {"first": _budget("board"), "again": MEMOIZED_SEC})
    body = grouped()
    print(f"grouped board {shape}: first {_ms(took['first'])}, again {_ms(took['again'])}; "
          f"{body['total_groups']} groups, {body['total_rows']} rows")
    assert body["total_groups"] > 0
    assert took["first"] <= _budget("board") and took["again"] <= MEMOIZED_SEC


MINUTES = 3


def _waiting_counts(cache, fleet):
    page = lambda q: cache.page(fleet.snap, fleet.schema, query=q, limit=1)["total"]  # noqa: E731
    times, totals = {}, []
    for minute in range(MINUTES):
        since = fgm_records.iso(NOW - 3600 + 60 * minute)
        query = f'status = "created" and timestamp < "{since}"'
        times[minute] = _timed(lambda q=query: totals.append(page(q)))
    times["plain"] = _timed(lambda: page('tags.health = "unstable"'))
    return times, totals


@pytest.mark.serial
def test_a_minute_keyed_waiting_count(warmed):
    """P1's ``status = "created" and timestamp < ago("1h")`` is rebuilt once a
    minute: each minute's literal is a fresh filtered order."""
    _, fleet, _ = warmed
    took, totals = _fastest(warmed, lambda cache: _waiting_counts(cache, fleet),
                            dict.fromkeys(range(MINUTES), _budget("waiting")))
    times = [took[minute] for minute in range(MINUTES)]
    print(f"minute-keyed waiting count: {[_ms(t) for t in times]} ({totals[0]} runs); "
          f"a time-free query's first build {_ms(took['plain'])}")
    assert totals[0] > 0
    assert max(times) <= _budget("waiting")


@pytest.mark.serial
def test_split_tallies_memory_per_outer_run(fleet):
    """P3: the split rollups' memory over the plain ones, per run with
    children (a board of its own: the shared one may hold the split)."""
    fleet, at = fleet
    views, snap, schema = JobViews(_warm(LeaderboardCache(now=lambda: at), fleet.snap)), fleet.snap, fleet.schema
    views.summary(snap, schema, fleet.live)
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        views.summary(snap, schema, fleet.live, SPLIT)
        grown = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    print(f"split={SPLIT} tallies: {grown / 1024:.0f} KB over {fleet.parents} runs with children, "
          f"{grown / fleet.parents:.0f} B each")
    assert grown / fleet.parents <= 64 * 1024
