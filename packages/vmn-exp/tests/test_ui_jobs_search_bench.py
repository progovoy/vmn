"""Plan 23 S8b bench: at 100k runs (20 jobs of 4500 trials, 4000 of them
live, 10k single runs) a Jobs view page searching every run
(``match_subtree``, the board's free-text clause, a new text each time)
answers in <= 100 ms. Timed, so serial; ``-s`` prints the numbers."""
import pytest
from leaderboard_fleet import T0, finished
from test_ui_search_index_bench import (
    SCHEMA,
    TEXTS,
    _BenchFleet,
    _board_clause,
    _p95,
    _timed,
)

from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb

JOBS, TRIALS, LIVE, SINGLES = 20, 4500, 4000, 10_000


@pytest.fixture(scope="module")
def fleet():
    fleet = _BenchFleet(7)
    fleet._names = {}
    fleet.seed_jobs(JOBS, TRIALS, T0, live=LIVE)
    for _ in range(SINGLES):
        fleet.append(state=finished(0))
    return fleet


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


@pytest.mark.serial
def test_jobs_view_search_over_every_run_at_100k(fleet):
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache()
    cache.page(snap, SCHEMA, limit=50, top=True)  # the base and the Jobs view order
    cache.search(snap, "warm", 20)  # the search index, as the refresher warms it
    texts = [f"{t}{suffix}" for suffix in ("", "0", "1") for t in TEXTS]
    pages = []
    timed = [_timed(lambda t=t: pages.append(cache.page(
        snap, SCHEMA, query=_board_clause(t), limit=50, top=True, match_subtree=True)))
        for t in texts]
    print(f"\nS8b jobs view search: p95 {_p95(timed) * 1000:.1f} ms, "
          f"max {max(timed) * 1000:.1f} ms; runs matched up to "
          f"{max(p['runs_matched'] for p in pages)}")
    assert _p95(timed) <= 0.100
    assert any(p["runs_matched"] >= TRIALS for p in pages)
