"""Plan 28 P1 bench: at 100k runs (20 outer runs x 5000, 400 live) an app's
attention counts are built once per generation within budget, answer a
repeat poll in microseconds, move to the next generation by its deltas (an
``ago()`` query included, within its minute) and rebuild an ``ago()``
query at most once a minute. Timed, so serial."""
import itertools
import time

import pytest
from bench_timing import fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, Fleet
from vmn_exp.ui.attention import attention_payload, queries_of
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

JOBS, INNERS, LIVE = 20, 5000, 400
EDITED = 5  # rows a new generation changes
BUDGETS = {"warm": 0.005, "built": 5.0, "moved": 1.0, "minute": 5.0, "jobs": 1.0}
SCHEMA = {"loss": {"goal": "min", "primary": True}}
ENTRIES = [
    {"key": "failed", "label": "failed", "query": 'status = "failed"', "level": "error"},
    {"key": "late", "label": "late", "query": 'status = "failed" and finished_at > ago("30m")',
     "level": "warn"},
]


def _timed(fn):
    start = time.perf_counter()
    out = fn()
    return time.perf_counter() - start, out


@pytest.fixture(scope="module")
def fleet():
    fleet = Fleet(28)
    fleet.seed_jobs(JOBS, INNERS, T0, live=LIVE)
    return fleet


@pytest.fixture
def clock():
    return FakeClock(start=T0)


def _counts(cache, snap):
    return [p["count"] for p in attention_payload(cache, snap, SCHEMA, ENTRIES)]


def _attempt(fleet, clock, edited):
    """One pass from a fresh cache: ``{step: seconds}``, each new generation
    changing *edited* rows no earlier pass changed."""
    cache, snap = LeaderboardCache(now=clock.now), fleet.snapshot()
    cache.page(snap, SCHEMA, limit=50)  # the board is warm
    took = {}
    took["built"], counts = _timed(lambda: _counts(cache, snap))
    took["warm"], again = _timed(lambda: _counts(cache, snap))
    assert counts == again and counts[0] >= counts[1] > 0
    for i in next(edited):
        fleet.edit(i, values={"loss": 0.1})
    nxt = fleet.snapshot()
    took["moved"], _ = _timed(lambda: _counts(cache, nxt))
    clock.advance(60)
    took["minute"], _ = _timed(lambda: _counts(cache, nxt))
    took["jobs"], _ = _timed(lambda: cache.attention.summaries(nxt, SCHEMA, queries_of(ENTRIES)))
    return took


@pytest.mark.serial
def test_attention_counts_are_built_once_and_moved_by_deltas(fleet, clock):
    edited = (range(JOBS + EDITED * a, JOBS + EDITED * (a + 1)) for a in itertools.count())
    took = fastest_each(lambda: _attempt(fleet, clock, edited), BUDGETS)
    print(f"\nattention at {len(fleet.rows)} runs: built {took['built'] * 1000:.0f} ms, "
          f"warm {took['warm'] * 1000:.2f} ms, next generation {took['moved'] * 1000:.0f} ms, "
          f"next minute {took['minute'] * 1000:.0f} ms, per outer run {took['jobs'] * 1000:.0f} ms")
    for step, budget in BUDGETS.items():
        assert took[step] <= budget, step
