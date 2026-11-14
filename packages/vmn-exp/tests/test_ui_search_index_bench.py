"""Plan 23 S8 bench: at 100k runs (20 jobs of 4500 trials, 10k single runs)
⌘K search answers in <= 50 ms and a list page with the board's free-text
clause in <= 100 ms (warm index, a new text each time), the index costs
<= 150 B per run, and a generation with 500 changed runs moves it on for a
fraction of a build. Timed, so serial; ``-s`` prints the numbers."""
import statistics
import time

import pytest
from bench_timing import fastest, fastest_each
from fakes.clock import FakeClock
from leaderboard_fleet import T0, finished, running
from search_fleet import TextFleet
from vmn_exp.ui.search_index import SearchIndex

from vmn_exp.ui import leaderboard_cache as lb

JOBS, TRIALS, SINGLES = 20, 4500, 10_000
N = JOBS * (TRIALS + 1) + SINGLES
SCHEMA = {"loss": {"goal": "min"}}
TEXTS = ["t1903", "grid7", "lr_layers_grid1", "0.01", "baseline", "alice", "@4242",
         "1.0.0-dev.r0123", "oom", "zzz", "adam", "t44", "grid12-t3", "nan", "warmup"]


def _board_clause(text):
    """What the web leaderboard sends for its search box (``searchClause``)."""
    return " or ".join(f'{f} ~ "{text}"' for f in ("name", "verstr", "note", "branch"))


class _BenchFleet(TextFleet):
    def _fold(self, i):
        spec = self.specs[i]
        if "text" not in spec:
            lr, layers = self.rng.choice(["0.1", "0.01", "0.001"]), self.rng.randrange(8)
            job = spec["parent"] and self._names.get(spec["parent"])
            name = f"{job}-t{i}" if job else f"lr_layers_grid{len(self._names)}"
            spec["text"] = {
                "name": name, "note": "baseline warmup" if i % 97 == 0 else None,
                "tags": {"stage": "dev"} if i % 13 == 0 else {},
                "extra": {"lr": lr, "layers": layers},
                "author": "alice@example.com",
                "command": ["python", "train.py", "--lr", lr, "--layers", str(layers)],
            }
            if not job:
                self._names[spec["verstr"]] = name
        return super()._fold(i)

    def _with_text(self, i, state):
        out = super()._with_text(i, state)
        if out and "error_summary" in out:
            out["error_summary"] = "CUDA error: out of memory (oom)"
        return out


def _timed(fn):
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


def _p95(samples):
    return statistics.quantiles(samples, n=20)[-1]


@pytest.fixture(scope="module")
def fleet():
    fleet = _BenchFleet(5)
    fleet._names = {}
    for _ in range(JOBS):
        job = fleet.append(state=running(T0))
        for _ in range(TRIALS):
            fleet.append(parent=job, state=fleet.rng.choice([finished(0), finished(1), None]))
    for _ in range(SINGLES):
        fleet.append(state=finished(0))
    for i in fleet.rng.sample(range(N), 4000):
        fleet.set_state(i, running(T0))
    return fleet


@pytest.mark.serial
def test_search_at_100k_runs(fleet):
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache(now=FakeClock(T0).now)
    cache.page(snap, SCHEMA, limit=50)  # the base, as a live dashboard has it
    build = _timed(lambda: cache._search.get(snap))
    index = cache._search.get(snap)
    per_run = index.nbytes() / N
    print(f"\nS8 index: build {build * 1000:.0f} ms, {per_run:.0f} B/run "
          f"({index.nbytes() / 1e6:.1f} MB)")
    assert per_run <= 150

    passes = []
    took = fastest_each(lambda: _searches(snap, passes), {"goto": 0.050, "listed": 0.100})
    goto, listed = passes[-1]
    print(f"S8 goto-run: p95 {_p95(goto) * 1000:.1f} ms, max {max(goto) * 1000:.1f} ms; "
          f"uncontended p95 {took['goto'] * 1000:.1f} ms")
    assert took["goto"] <= 0.050
    print(f"S8 list text search: p95 {_p95(listed) * 1000:.1f} ms; "
          f"uncontended p95 {took['listed'] * 1000:.1f} ms")
    assert took["listed"] <= 0.100


def _searches(snap, passes):
    """⌘K and list text searches on a fresh warm cache: their p95 seconds;
    the samples appended to *passes*."""
    cache = lb.LeaderboardCache(now=FakeClock(T0).now)
    cache.page(snap, SCHEMA, limit=50)
    cache._search.get(snap)
    goto = [_timed(lambda t=t: cache.search(snap, t, 20)) for t in TEXTS * 3]
    texts = [f"{t}{suffix}" for suffix in ("", "0", "1") for t in TEXTS]
    listed = [_timed(lambda t=t: cache.page(snap, SCHEMA, query=_board_clause(t), limit=50))
              for t in texts]
    passes.append((goto, listed))
    return {"goto": _p95(goto), "listed": _p95(listed)}


@pytest.mark.serial
def test_list_text_search_without_the_index_for_reference(fleet, monkeypatch):
    snap = fleet.snapshot()
    cache = lb.LeaderboardCache(now=FakeClock(T0).now)
    cache.page(snap, SCHEMA, limit=50)
    monkeypatch.setattr(cache, "_candidates", lambda *args, **kwargs: None)
    listed = [_timed(lambda t=t: cache.page(snap, SCHEMA, query=_board_clause(t), limit=50))
              for t in TEXTS]
    print(f"\nS8 list text search, no index (today): p95 {_p95(listed) * 1000:.1f} ms")


@pytest.mark.serial
def test_a_generation_of_500_changed_runs_moves_the_index_on(fleet):
    passes = []
    excess = fastest(lambda: _generations(fleet, passes), budget=0.0)
    build, moves = passes[-1]
    print(f"\nS8 next generation (500 changed): move median "
          f"{statistics.median(moves) * 1000:.0f} ms, max {max(moves) * 1000:.0f} ms "
          f"vs build {build * 1000:.0f} ms")
    assert excess < 0, (moves, build)


def _generations(fleet, passes):
    """How far the slowest of 3 generations' moves went past half a build
    of the fleet as it is; build and moves appended to *passes*."""
    snap = fleet.snapshot()
    build = min(_timed(lambda: SearchIndex.build(snap)) for _ in range(2))
    index = SearchIndex.build(snap)
    moves = []
    for _ in range(3):
        rng = fleet.rng
        for i in rng.sample(range(N), 300):
            fleet.edit(i, values=fleet._values())
        for i in rng.sample(range(N), 100):
            fleet.set_state(i, finished(rng.choice([0, 1])))
        for i in rng.sample(range(N), 50):
            fleet.retext(i)
        for _ in range(50):
            fleet.append(state=running(T0))
        snap = fleet.snapshot()
        start = time.perf_counter()
        index = index.moved(snap)
        moves.append(time.perf_counter() - start)
    passes.append((build, moves))
    return max(moves) - build / 2
