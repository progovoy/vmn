"""Plan 28 T2a bench: at 100k runs (2000 outer runs x 50, half of them live,
400 inner runs live) a ``/metrics`` scrape of a warm board (what the
refresher's warming leaves) costs a walk of the outer runs, not of the runs:
the counts and rollups are the board's cached ones, the job rollups rebuilt
at most once a minute as the Outer runs view's are. Timed, so serial."""
import datetime
import time

import pytest
from leaderboard_fleet import T0, Fleet
from prometheus_parse import label_sets, parse
from vmn_exp.core import status as status_mod
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.prometheus import exposition
from vmn_exp.ui.rollup_gauges import MAX_OUTER_RUNS, app_samples, new_families

JOBS, INNERS, LIVE = 1000, 50, 400
ENTRIES = [{"key": "failed_any", "label": "failed", "query": 'status = "failed"',
            "level": "error"}]
LABELS = {"workspace": "ws", "app": "app"}


def _timed(fn):
    start = time.perf_counter()
    out = fn()
    return time.perf_counter() - start, out


@pytest.fixture
def clock(monkeypatch):
    at = {"now": T0}
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or at["now"])
    return at


def _fleet():
    fleet = Fleet(29)
    fleet.seed_jobs(JOBS, INNERS - 1, T0, live=LIVE)
    for _ in range(JOBS):
        outer = fleet.append(state=fleet.ended(T0, code=0))
        for _ in range(INNERS - 1):
            fleet.append(parent=outer, state=fleet.ended(T0))
    return fleet


def _scrape(cache, snap):
    families = new_families()
    for gauge, labels, value in app_samples(LABELS, cache, snap, {}, ENTRIES, status_mod._now(),
                                            24 * 3600):
        families[gauge].add(labels, value)
    return exposition(families.values())


@pytest.mark.serial
def test_a_scrape_of_a_warm_100k_run_board_walks_only_its_outer_runs(clock):
    snap = _fleet().snapshot()
    cache = LeaderboardCache()
    warm, _ = _timed(lambda: cache.warm(snap))  # the refresher, off the scrape
    first, text = _timed(lambda: _scrape(cache, snap))
    again, _ = _timed(lambda: _scrape(cache, snap))
    clock["now"] = T0 + datetime.timedelta(minutes=1)
    minute, _ = _timed(lambda: _scrape(cache, snap))
    print(f"\nwarm {warm * 1000:.0f} ms; scrape {first * 1000:.0f} ms, again "
          f"{again * 1000:.1f} ms, next minute {minute * 1000:.0f} ms")
    outer_runs = {s["outer_run"] for s in label_sets(parse(text), "vmn_job_runs")}
    assert len(outer_runs) == MAX_OUTER_RUNS
    assert first <= 1.0, first
    assert again <= 0.05, again
    assert minute <= 0.5, minute
