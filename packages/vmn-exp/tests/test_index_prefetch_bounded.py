"""A warm (or cold-dropped) index's lazy records read their stored parts a
chunk at a time. The records a chunk read but nobody asked for must not stay
held: each refresh touches the scattered live runs, so over a server's life
the leftovers grew to every record's head and fold JSON (fgm: 705k runs,
tens of GiB after the index had loaded)."""
import tracemalloc

from test_index_lean_tables import APP, FINISHED, _entry, _run
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_store_reads import _CHUNK, _Prefetch
from vmn_exp.snapshot import LocalSnapshotStorage

N = 20_000
PART = 2_000  # bytes of one record's stored JSON
STRIDE = 200  # a live run every STRIDE records, like a fleet's scattered heartbeats
WARM_RUNS, WARM_STRIDE = 600, 50


class _Store:
    def __init__(self):
        self.reads = []

    def records_parts(self, app_name, seqs):
        self.reads.append(list(seqs))
        return {key: (f'{{"k": "{key}"}}', key + "x" * PART, None) for key in seqs}


def _keys():
    return [f"r{i:06d}" for i in range(N)]


def test_scattered_asks_hold_at_most_a_chunk_of_unasked_parts():
    keys = _keys()
    fetch = _Prefetch(_Store(), "app", dict.fromkeys(keys, 1))
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        handed = [fetch(key) for key in keys[::STRIDE]]
        held = tracemalloc.get_traced_memory()[0] - before
    finally:
        tracemalloc.stop()
    used = len(handed) * PART
    assert held - used <= 2 * _CHUNK * PART, f"{(held - used) / 1e6:.1f} MB held unasked"


def test_a_part_read_but_dropped_unasked_is_read_again_when_asked():
    keys = _keys()
    store = _Store()
    fetch = _Prefetch(store, "app", dict.fromkeys(keys, 1))
    fetch(keys[0])  # reads keys[0:_CHUNK]
    fetch(keys[10 * _CHUNK])  # another chunk
    head, data, state = fetch(keys[5])
    assert data.startswith(keys[5]) and head == f'{{"k": "{keys[5]}"}}'


def test_a_warm_refresh_reads_only_the_scattered_records_it_touches(tmp_path, monkeypatch):
    """Dropping unasked parts must not turn each scattered ask into a whole
    chunk's read: a warm index reads just the records its refresh touches."""
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    runs = [f"0.0.1-dev.abc.r{i}" for i in range(WARM_RUNS)]
    for i, verstr in enumerate(runs):
        _run(st, verstr, i % 60, FINISHED)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    touched = runs[::WARM_STRIDE]
    for verstr in touched:
        _entry(st, verstr, "metrics", 59, values={"loss": 0.5})
    read = []
    parts = SqliteStore.records_parts
    monkeypatch.setattr(SqliteStore, "records_parts",
                        lambda self, app, seqs: read.extend(seqs) or parts(self, app, seqs))
    warm = ExperimentIndex(st, APP, cache_path=db)
    warm.snapshot()
    warm.wait_revalidated()
    assert set(touched) <= set(read)
    assert len(read) <= 2 * len(touched)


def test_an_in_order_walk_still_reads_whole_chunks():
    keys = _keys()[:4 * _CHUNK]
    store = _Store()
    fetch = _Prefetch(store, "app", dict.fromkeys(keys, 1))
    assert all(fetch(key)[1].startswith(key) for key in keys)
    assert len(store.reads) == 4
