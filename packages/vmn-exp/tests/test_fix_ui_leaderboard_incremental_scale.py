"""Scale guard: at 20k runs with a few dozen changing per index generation,
serving a new generation re-derives, re-filters and re-places only the
changed rows (and their ancestors) — never every row. Counts calls instead
of timing, so it cannot flake on a loaded box."""
import datetime
import math
import sys

import pytest

from leaderboard_fleet import T0, Fleet, finished, running
from vmn_exp.core import status as status_mod
from vmn_exp.ui import leaderboard_cache as lb
from vmn_exp.ui.readers.experiments import facets

N = 20000
LIVE = 40
SWEEPS = 5
EDITS = 10  # metric edits, new children, finishes, starts, archive toggles
CHANGED = LIVE + EDITS  # every live run heartbeats each generation
BOUND = 10 * (CHANGED + SWEEPS)
GENERATIONS = 3


class _Row(dict):
    """A row that counts how often it is read."""

    reads = 0

    def get(self, *args):
        _Row.reads += 1
        return dict.get(self, *args)

    def __getitem__(self, key):
        _Row.reads += 1
        return dict.__getitem__(self, key)


class _CountedFleet(Fleet):
    def _fold(self, i):
        return _Row(super()._fold(i))


def _count_everywhere(monkeypatch, name, counts, measure=lambda args: 1, wrap=None):
    """Count calls of *name* in every loaded ``vmn_exp`` module that uses it."""
    originals = {id(getattr(m, name)) for k, m in list(sys.modules.items())
                 if k.startswith("vmn_exp") and callable(getattr(m, name, None))}
    for key, module in list(sys.modules.items()):
        real = getattr(module, name, None) if key.startswith("vmn_exp") else None
        if real is None or id(real) not in originals:
            continue

        def counted(*args, _real=real, **kwargs):
            counts[name] = counts.get(name, 0) + measure(args)
            out = _real(*args, **kwargs)
            return wrap(out) if wrap else out

        monkeypatch.setattr(module, name, counted)


def _counted_key(counts):
    def wrap(out):
        key, ranked = out

        def counted(row):
            counts["key"] = counts.get("key", 0) + 1
            return key(row)

        return counted, ranked

    return wrap


def _serve(cache, snap):
    schema = {"loss": {"goal": "min"}}
    cache.page(snap, schema, limit=50)
    cache.page(snap, schema, sort="loss", order="asc", offset=100, limit=50)
    cache.page(snap, schema, query="metrics.loss < 0.5", limit=50)
    cache.page(snap, schema, status="running,stuck", limit=50)
    cache.page(snap, schema, sort="timestamp", limit=50)
    cache.page(snap, schema, last=20, limit=50)
    cache.columns(snap, schema, ["metrics.loss", "status"], sort="loss", limit=100)
    cache.facets(snap)
    cache.facets(snap, archived=True)


def _next_generation(fleet, roots, live, now, step):
    for i in live:
        fleet.set_state(i, running(now))
    rng = fleet.rng
    for i in rng.sample(range(N), 4):
        fleet.edit(i, values=fleet._values())
    for _ in range(3):
        fleet.append(parent=rng.choice(roots), state=finished())
    fleet.set_state(rng.randrange(SWEEPS, N), finished(1))
    fleet.set_state(rng.randrange(SWEEPS, N), None)
    fleet.edit(SWEEPS + step, archived=True)
    return fleet.snapshot()


@pytest.fixture
def fleet():
    fleet = _CountedFleet(11)
    roots = fleet.seed(N, T0, sweeps=SWEEPS, live=0)
    live = fleet.rng.sample(range(SWEEPS, N), LIVE)
    for i in live:
        fleet.set_state(i, running(T0))
    return fleet, roots, live


def test_a_new_generation_costs_the_changed_rows_not_every_row(monkeypatch, fleet):
    fleet, roots, live = fleet
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache = lb.LeaderboardCache(bucket_sec=2)
    _serve(cache, fleet.snapshot())

    counts = {}
    _count_everywhere(monkeypatch, "annotate_rows", counts)
    _count_everywhere(monkeypatch, "status_fields", counts)
    _count_everywhere(monkeypatch, "sort_rows", counts, lambda args: len(args[0]))
    _count_everywhere(monkeypatch, "apply_filters", counts, lambda args: len(args[0]))
    _count_everywhere(monkeypatch, "children_by_parent", counts, lambda args: len(args[0]))
    _count_everywhere(monkeypatch, "order_key", counts, wrap=_counted_key(counts))
    log_n = math.ceil(math.log2(N))
    for step in range(GENERATIONS):
        snap = _next_generation(fleet, roots, live, T0, step)
        counts.clear()
        _serve(cache, snap)
        assert counts.get("annotate_rows", 0) == 0
        assert counts.get("status_fields", 0) <= BOUND
        assert counts.get("sort_rows", 0) <= BOUND
        assert counts.get("apply_filters", 0) <= 2 * BOUND
        assert counts.get("children_by_parent", 0) <= BOUND
        assert counts.get("key", 0) <= 6 * 4 * (CHANGED + SWEEPS) * log_n


def test_facets_of_a_new_generation_read_only_the_changed_rows(monkeypatch, fleet):
    fleet, roots, live = fleet
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache = lb.LeaderboardCache(bucket_sec=2)
    cache.facets(fleet.snapshot())
    cache.facets(fleet.snapshot(), archived=True)
    for step in range(GENERATIONS):
        snap = _next_generation(fleet, roots, live, T0, step)
        _Row.reads = 0
        want = facets([r for r in snap.rows if not r.get("archived")])
        assert _Row.reads > N  # the full scan reads every row
        _Row.reads = 0
        assert cache.facets(snap) == want
        cache.facets(snap, archived=True)
        assert _Row.reads <= BOUND


def test_live_rows_advancing_in_time_still_cost_only_the_live_rows(monkeypatch, fleet):
    fleet, roots, live = fleet
    cache = lb.LeaderboardCache(bucket_sec=2)
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    _serve(cache, fleet.snapshot())
    counts = {}
    _count_everywhere(monkeypatch, "status_fields", counts)
    _count_everywhere(monkeypatch, "apply_filters", counts, lambda args: len(args[0]))
    for step in range(1, GENERATIONS + 1):
        now = T0 + datetime.timedelta(seconds=30 * step)
        monkeypatch.setattr(status_mod, "_now", lambda now=None, _at=now: now or _at)
        snap = _next_generation(fleet, roots, live[: LIVE // 2], now, step)
        counts.clear()
        _serve(cache, snap)
        assert counts.get("status_fields", 0) <= BOUND
        assert counts.get("apply_filters", 0) <= 2 * BOUND


def test_an_order_not_asked_for_a_few_generations_is_moved_on_not_rebuilt(monkeypatch, fleet):
    """The dashboard's mix asks for many orderings (every metric, both
    directions, queries), each only now and then; a new generation per second
    means an order is rarely asked for in two consecutive ones. It is moved on
    from the last generation it was served in, across the deltas since."""
    fleet, roots, live = fleet
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or T0)
    cache = lb.LeaderboardCache(bucket_sec=2)
    schema = {"loss": {"goal": "min"}}
    orders = [dict(sort=m, order=o) for m in ("loss", "acc") for o in ("asc", "desc")]
    orders += [dict(query=f"metrics.loss < {x}") for x in (0.2, 0.4, 0.6, 0.8)]
    orders += [dict(sort="acc", query=f"metrics.loss > {x}") for x in range(40)]
    snap = fleet.snapshot()
    for kw in orders:
        cache.page(snap, schema, limit=50, **kw)

    counts = {}
    _count_everywhere(monkeypatch, "sort_rows", counts, lambda args: len(args[0]))
    for step in range(5):
        snap = _next_generation(fleet, roots, live, T0, step)
        cache.page(snap, schema, limit=50)  # only the default order each generation
    counts.clear()
    for kw in orders:  # every other order comes back, several generations on
        want = lb.LeaderboardCache(bucket_sec=2).page(snap, schema, limit=50, **kw)
        counts_before = counts.get("sort_rows", 0)
        assert cache.page(snap, schema, limit=50, **kw) == want
        counts["served"] = counts.get("served", 0) + counts.get("sort_rows", 0) - counts_before
    assert counts.get("served", 0) <= len(orders) * BOUND
