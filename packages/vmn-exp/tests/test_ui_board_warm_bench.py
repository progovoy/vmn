"""What the refresher's board warm-up costs at production scale (46k runs:
outer runs of 27k inner runs plus 19k single runs, 50 live), on the first
generation and on each next one (a refresh's few new and changed records),
and what the default first pages cost a request afterwards. Timed, so serial."""
import time

import pytest
from bench_timing import fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from test_ui_board_warm import DEFAULT, TOPS
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

CLOCK = FakeClock(start=T0)
INNERS, SINGLES, LIVE = 27_000, 19_000, 50
GENERATIONS = 10
NEW_PER_GENERATION = 20
BUDGETS = {"request": 0.05, "hit": 0.05, "next": 0.5}


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _ms(seconds):
    return round(seconds * 1000, 1)


def _requests(cache, snap):
    """The first browser requests: facets, then each top view's first page."""
    times = [_timed(lambda: cache.facets_payload(snap))]
    times += [_timed(lambda top=top: cache.page(snap, {}, top=top, **DEFAULT)) for top in TOPS]
    return times


@pytest.mark.serial
def test_the_board_warm_up_is_bounded_and_makes_the_first_pages_memo_hits():
    fleet = Fleet(7)
    jobs = fleet.seed_jobs(3, INNERS // 3, T0, live=LIVE)
    for _ in range(SINGLES):
        fleet.append(state=fleet.ended(T0))
    snap = fleet.snapshot()

    cold_cache = LeaderboardCache(now=CLOCK.now)
    cold_requests = _requests(cold_cache, snap)

    passes = []
    took = fastest_each(lambda: _warm_pass(fleet, jobs, passes), BUDGETS)
    first, warm_requests, nexts, hits = passes[-1]

    print(f"\n{len(fleet.rows)} runs: cold first requests (no warm-up) ms {[_ms(t) for t in cold_requests]}; "
          f"first warm {_ms(first)} ms, then requests ms {[_ms(t) for t in warm_requests]}; "
          f"next-generation warm ms {[_ms(t) for t in nexts]}; slowest request after each {[_ms(t) for t in hits]}; "
          f"uncontended slowest request {_ms(took['request'])} ms, hit {_ms(took['hit'])} ms, "
          f"next warm {_ms(took['next'])} ms")
    assert took["request"] <= BUDGETS["request"], warm_requests
    assert took["hit"] <= BUDGETS["hit"], hits
    assert took["next"] <= BUDGETS["next"], nexts


def _warm_pass(fleet, jobs, passes):
    """A fresh cache warmed on the fleet as it is, then GENERATIONS new ones:
    ``{step: slowest seconds}``, the pass's times appended to *passes*."""
    snap = fleet.snapshot()
    cache = LeaderboardCache(now=CLOCK.now)
    first = _timed(lambda: cache.warm(snap))
    warm_requests = _requests(cache, snap)

    nexts, hits = [], []
    for _ in range(GENERATIONS):
        for i in range(NEW_PER_GENERATION):
            fleet.append(parent=jobs[i % 3] if i % 2 else None, state=fleet.ended(T0))
        snap = fleet.snapshot()
        nexts.append(_timed(lambda snap=snap: cache.warm(snap)))
        hits.append(max(_requests(cache, snap)))
    passes.append((first, warm_requests, nexts, hits))
    return {"request": max(warm_requests), "hit": max(hits), "next": max(nexts)}
