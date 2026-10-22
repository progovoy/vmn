"""What the refresher's board warm-up costs at production scale (46k runs:
outer runs of 27k inner runs plus 19k single runs, 50 live), on the first
generation and on each next one (a refresh's few new and changed records),
and what the default first pages cost a request afterwards. Timed, so serial."""
import time

import pytest
from leaderboard_fleet import T0, Fleet
from test_ui_board_warm import DEFAULT, TOPS
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

from vmn_exp.core import status as status_mod

INNERS, SINGLES, LIVE = 27_000, 19_000, 50
GENERATIONS = 10
NEW_PER_GENERATION = 20


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _ms(seconds):
    return round(seconds * 1000, 1)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)


def _requests(cache, snap):
    """The first browser requests: facets, then each top view's first page."""
    times = [_timed(lambda: cache.facets_payload(snap))]
    times += [_timed(lambda top=top: cache.page(snap, {}, top=top, **DEFAULT)) for top in TOPS]
    return times


@pytest.mark.serial
def test_the_board_warm_up_is_bounded_and_makes_the_first_pages_memo_hits(frozen):
    fleet = Fleet(7)
    jobs = fleet.seed_jobs(3, INNERS // 3, T0, live=LIVE)
    for _ in range(SINGLES):
        fleet.append(state=fleet.ended(T0))
    snap = fleet.snapshot()

    cold_cache = LeaderboardCache()
    cold_requests = _requests(cold_cache, snap)

    cache = LeaderboardCache()
    first = _timed(lambda: cache.warm(snap))
    warm_requests = _requests(cache, snap)

    nexts, hits = [], []
    for _ in range(GENERATIONS):
        for i in range(NEW_PER_GENERATION):
            fleet.append(parent=jobs[i % 3] if i % 2 else None, state=fleet.ended(T0))
        snap = fleet.snapshot()
        nexts.append(_timed(lambda snap=snap: cache.warm(snap)))
        hits.append(max(_requests(cache, snap)))

    print(f"\n{len(snap.rows)} runs: cold first requests (no warm-up) ms {[_ms(t) for t in cold_requests]}; "
          f"first warm {_ms(first)} ms, then requests ms {[_ms(t) for t in warm_requests]}; "
          f"next-generation warm ms {[_ms(t) for t in nexts]}; slowest request after each {[_ms(t) for t in hits]}")
    assert max(warm_requests) <= 0.05, warm_requests
    assert max(hits) <= 0.05, hits
    assert max(nexts) <= 0.5, nexts
