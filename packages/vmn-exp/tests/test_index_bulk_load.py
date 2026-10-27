"""A cold remote load stays linear in the store's size.

It reads newest first, so each chunk of older records sorts before the ones
loaded: the next snapshot re-numbers and rebuilds every row, and the store
re-numbers every persisted row. Done per 500-record chunk that was O(N) per
chunk — at 497k runs a projected ten hours. Publishing waits until the
records loaded since are a share of those published, and the store leaves
the numbering to the end of the load."""
import sqlite3
import threading
import time

from cold_store import APP, ColdStore

from vmn_exp.core import index as index_module
from vmn_exp.core import index_snapshot
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore

N = 50_000


def _cold_load(tmp_path, n, monkeypatch):
    """A cold journaled index loaded from a fake store of *n* runs, with
    ``[(records loaded, rows built)]`` of each snapshot built meanwhile."""
    builds, index = [], None
    real = index_snapshot.RowCache.snapshot

    def counted(self, app_name, generation, order, records, *args, **kwargs):
        builds.append((len(records), len(order)))
        return real(self, app_name, generation, order, records, *args, **kwargs)

    monkeypatch.setattr(index_snapshot.RowCache, "snapshot", counted)
    index = ExperimentIndex(ColdStore(n), APP, cache_path=str(tmp_path / "idx.sqlite"),
                            full_sweep_sec=3600)
    index.journaled = True
    index.reconcile()
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        index.refresh()
        snap = index.published
        if snap is not None and len(snap.rows) == n and index.freshness()["phase"] == "idle":
            return index, builds
    raise AssertionError("the cold load did not finish")


def test_rows_built_per_record_loaded_stay_flat_as_the_load_grows(tmp_path, monkeypatch):
    _, builds = _cold_load(tmp_path, N, monkeypatch)
    late = [(loaded, rows) for loaded, rows in builds if loaded > N // 2]
    loaded_late = N - N // 2
    # Each snapshot rebuilds every row (the order grew at its front): what
    # the second half's snapshots built, per record it loaded.
    assert sum(rows for _, rows in late) / loaded_late <= 25, len(late)


def test_a_cold_load_leaves_the_persisted_rows_numbered_by_rank(tmp_path, monkeypatch):
    index, _ = _cold_load(tmp_path, 3_000, monkeypatch)
    conn = sqlite3.connect(index.path)
    ranks = conn.execute("SELECT idx FROM exp_rows WHERE app = ? ORDER BY timestamp, key",
                         (APP,)).fetchall()
    assert [idx for (idx,) in ranks] == list(range(1, 3_001))
    assert [r["idx"] for r in index.rows()] == list(range(1, 3_001))


def _record(i):
    from vmn_exp.core.fold import new_fold
    from vmn_exp.core.index_record import new_record

    record = new_record()
    record.update(meta={"verstr": f"v{i:05d}", "timestamp": f"2026-01-01T{i:08d}"},
                  fold=new_fold(), meta_sig=[1, 1.0, "e"])
    return record


def _ranks(store):
    conn = store.connection()[0]
    return [idx for (idx,) in conn.execute(
        "SELECT idx FROM exp_rows WHERE app = ? ORDER BY timestamp, key", ("a",))]


def test_numbering_later_skips_renumbering_until_asked(tmp_path):
    store = SqliteStore(str(tmp_path / "s.sqlite"))
    store.number_later("a", True)
    for start in (40, 30, 20, 10, 0):  # newest first: each save sorts before the last
        chunk = {f"k{i:05d}": _record(i) for i in range(start, start + 10)}
        assert store.save("a", chunk, (), {})
    assert _ranks(store) == [None] * 40 + list(range(1, 11))  # only the first save numbered
    store.number_later("a", False)
    assert _ranks(store) == list(range(1, 51))


def test_a_save_numbers_on_only_when_no_row_was_left_unnumbered(tmp_path):
    store = SqliteStore(str(tmp_path / "s.sqlite"))
    store.number_later("a", True)
    store.save("a", {f"k{i:05d}": _record(i) for i in range(10, 20)}, (), {})
    store.save("a", {f"k{i:05d}": _record(i) for i in range(0, 10)}, (), {})
    fresh = SqliteStore(str(tmp_path / "s.sqlite"))  # a restart: the deferral is gone
    fresh.save("a", {f"k{i:05d}": _record(i) for i in range(20, 25)}, (), {})
    assert _ranks(fresh) == list(range(1, 26))
