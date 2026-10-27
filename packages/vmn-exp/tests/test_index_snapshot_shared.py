"""Successive index snapshots share their per-verstr maps instead of copying
them (plan 26 F00): a generation that changed 50 of 50k runs costs those 50,
not 50k entries per map. At 486k runs one copy of one map was ~10 ms and
~21 MB, ~100-170 MB a generation at about a generation a second."""
import random
import tracemalloc

from vmn_exp.core.fold import new_fold
from vmn_exp.core.index_snapshot import RowCache
from vmn_exp.core.shared_map import SharedMap

APP = "app"
N, GENERATIONS, CHANGES = 50_000, 100, 50


def _record(i, beat=0):
    verstr = f"0.0.1-dev.abc.r{i}"
    fold = new_fold()
    return {
        "meta": {"verstr": verstr, "timestamp": f"2026-01-01T00:00:00.{i:06d}Z",
                 "parent": None},
        "fold": fold,
        "rs_sig": [10, 1_800_000_000.0 + beat, f"e{beat}"],
        "run_state": {"state": "running", "heartbeat_seq": beat},
    }


def _fleet(n=N):
    order = [f"k{i:06d}" for i in range(n)]
    return order, {key: _record(i) for i, key in enumerate(order)}


def _maps(snap):
    return [snap.run_states, snap.edges, snap.create_notes, snap.run_state_observed_at,
            snap._by_verstr]


def _retained(build):
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        kept = build()
        return tracemalloc.get_traced_memory()[0] - before, kept
    finally:
        tracemalloc.stop()


def _todays_generation(snap):
    """What a snapshot cost before F00: a dict copy per map and a rows tuple."""
    cost, _ = _retained(lambda: [dict(m.items()) for m in _maps(snap)] + [tuple(list(snap.rows))])
    return cost


def _heartbeats(cache, order, records, rng):
    """The generations of CHANGES heartbeats each (the records changed
    beforehand: only the snapshots are measured)."""
    beats = []
    for gen in range(2, GENERATIONS + 2):
        touched = {order[rng.randrange(N)] for _ in range(CHANGES)}
        beats.append({key: dict(records[key], **{
            k: v for k, v in _record(int(key[1:]), gen).items() if k in ("rs_sig", "run_state")})
            for key in touched})

    def generations():
        kept = []
        for gen, beat in enumerate(beats, 2):
            records.update(beat)
            kept.append(cache.snapshot(APP, gen, order, records, set(beat)))
        return kept
    return generations


def test_a_generation_shares_the_maps_of_the_last():
    order, records = _fleet(1000)
    cache = RowCache()
    first = cache.snapshot(APP, 1, order, records)
    key = order[5]
    records[key] = dict(records[key], run_state={"state": "running", "heartbeat_seq": 9})
    second = cache.snapshot(APP, 2, order, records, {key})
    assert all(isinstance(m, SharedMap) for m in _maps(second))
    verstr = records[key]["meta"]["verstr"]
    assert second.run_states[verstr] == {"state": "running", "heartbeat_seq": 9}
    assert first.run_states[verstr] == {"state": "running", "heartbeat_seq": 0}
    assert second.rows is first.rows  # no row changed: the same tuple
    assert dict(second.edges.items()) == dict(first.edges.items())


def test_heartbeat_generations_cost_a_small_fraction_of_copying_every_map():
    order, records = _fleet()
    cache = RowCache()
    first = cache.snapshot(APP, 1, order, records)
    today = _todays_generation(first)
    cost, kept = _retained(_heartbeats(cache, order, records, random.Random(5)))
    assert len(kept[-1].rows) == N
    assert cost <= 0.02 * GENERATIONS * today, (cost, today)


def test_refolded_rows_cost_their_maps_little_beyond_the_rows_tuple():
    """The rows tuple is still built whenever a row changed (plan 26 F00:
    shared only if F0 shows it matters); the maps beside it cost little."""
    order, records = _fleet()
    cache = RowCache()
    first = cache.snapshot(APP, 1, order, records)
    today = _todays_generation(first)
    rows_tuple, _ = _retained(lambda: tuple(list(first.rows)))
    rng = random.Random(9)

    def generations():
        kept = []
        for gen in range(2, GENERATIONS + 2):
            touched = {order[rng.randrange(N)] for _ in range(CHANGES)}
            for key in touched:
                cache.pop(key)  # refolded, as a dirty record is
            kept.append(cache.snapshot(APP, gen, order, records, touched))
        return kept

    cost, _ = _retained(generations)
    assert cost - GENERATIONS * rows_tuple <= 0.02 * GENERATIONS * today, (cost, today)
