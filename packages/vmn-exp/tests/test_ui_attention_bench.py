"""Plan 28 P1 bench: at 100k runs (20 outer runs x 5000, 400 live) an app's
attention counts are built once per generation within budget, answer a
repeat poll in microseconds, move to the next generation by its deltas (an
``ago()`` query included, within its minute) and rebuild an ``ago()``
query at most once a minute. Timed, so serial."""
import datetime
import time

import pytest
from leaderboard_fleet import T0, Fleet
from vmn_exp.core import status as status_mod
from vmn_exp.ui.attention import attention_payload, queries_of
from vmn_exp.ui.leaderboard_cache import LeaderboardCache

JOBS, INNERS, LIVE = 20, 5000, 400
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
def clock(monkeypatch):
    at = {"now": T0}
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or at["now"])
    return at


def _counts(cache, snap):
    return [p["count"] for p in attention_payload(cache, snap, SCHEMA, ENTRIES)]


@pytest.mark.serial
def test_attention_counts_are_built_once_and_moved_by_deltas(fleet, clock):
    cache, snap = LeaderboardCache(), fleet.snapshot()
    cache.page(snap, SCHEMA, limit=50)  # the board is warm
    built, counts = _timed(lambda: _counts(cache, snap))
    warm, again = _timed(lambda: _counts(cache, snap))
    for i in range(JOBS, JOBS + 5):
        fleet.edit(i, values={"loss": 0.1})
    nxt = fleet.snapshot()
    moved, _ = _timed(lambda: _counts(cache, nxt))
    clock["now"] = T0 + datetime.timedelta(minutes=1)
    minute, _ = _timed(lambda: _counts(cache, nxt))
    jobs, _ = _timed(lambda: cache.attention.summaries(nxt, SCHEMA, queries_of(ENTRIES)))
    print(f"\nattention at {len(fleet.rows)} runs: built {built * 1000:.0f} ms, "
          f"warm {warm * 1000:.2f} ms, next generation {moved * 1000:.0f} ms, "
          f"next minute {minute * 1000:.0f} ms, per outer run {jobs * 1000:.0f} ms")
    assert counts == again and counts[0] >= counts[1] > 0
    assert warm <= 0.005
    assert built <= 5.0
    assert moved <= 1.0
    assert minute <= 5.0
    assert jobs <= 1.0
