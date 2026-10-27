"""Scale guard: at 50k runs with live runs making a new index generation
about every second, the app status summary of a generation costs the
changed and live rows, never every row. Counts calls of the per-row status
read instead of timing, so it cannot flake on a loaded box."""
import sys

import pytest
from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.status_summary import status_summary

from vmn_exp.core import status as status_mod

N = 50000
LIVE = 40
SWEEPS = 5
EDITS = 10  # metric edits, new children, finishes, starts, an archive toggle
BOUND = 4 * (LIVE + SWEEPS + EDITS)
GENERATIONS = 4


def _count_counted_status(monkeypatch, counts):
    """Count :func:`counted_status` calls in every ``vmn_exp`` module using it."""
    name = "counted_status"
    for key, module in list(sys.modules.items()):
        real = getattr(module, name, None) if key.startswith("vmn_exp") else None
        if not callable(real):
            continue

        def counted(row, _real=real):
            counts[0] += 1
            return _real(row)

        monkeypatch.setattr(module, name, counted)


def _next_generation(fleet, roots, live, step):
    for i in live:
        fleet.set_state(i, running(T0))
    rng = fleet.rng
    for i in rng.sample(range(N), 4):
        fleet.edit(i, values=fleet._values())
    for _ in range(3):
        fleet.append(parent=rng.choice(roots), state=finished())
    fleet.set_state(rng.randrange(SWEEPS, N), fleet.ended(T0, code=1))
    fleet.set_state(rng.randrange(SWEEPS, N), None)
    fleet.edit(SWEEPS + step, archived=True)
    return fleet.snapshot()


@pytest.fixture
def fleet():
    fleet = Fleet(12)
    roots = fleet.seed(N, T0, sweeps=SWEEPS, live=0)
    live = fleet.rng.sample(range(SWEEPS, N), LIVE)
    for i in live:
        fleet.set_state(i, running(T0))
    return fleet, roots, live


def test_a_new_generation_counts_the_changed_and_live_rows_only(monkeypatch, fleet):
    fleet, roots, live = fleet
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache = LeaderboardCache()
    cache.status_summary(fleet.snapshot(), T0)  # warm-up: one full count
    counts = [0]
    _count_counted_status(monkeypatch, counts)
    for step in range(GENERATIONS):
        snap = _next_generation(fleet, roots, live, step)
        counts[0] = 0
        body = cache.status_summary(snap, T0)
        assert counts[0] <= BOUND, step
        assert body == status_summary(LeaderboardCache().rows(snap), T0)
