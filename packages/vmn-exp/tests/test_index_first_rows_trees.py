"""A warm restart's first rows hold whole trees: beside the newest runs, their
ancestors up to the root and the newest outer runs (each with a child, so it
reads as one). The newest runs of a sweep-heavy app are all trials: without
them the Outer runs view answered "No runs yet" until every row was read."""
import sqlite3
import threading

import pytest

import vmn_exp.core.index as index_module
from journal_index_helpers import APP, FINISHED, storage
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore

FIRST = 10
TRIALS = 15


def _save(st, verstr, second, parent=None):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{second:02d}Z"}
    if parent:
        meta["parent"] = parent
    st.save(APP, verstr, meta, {})
    st.save_file(APP, verstr, "run_state.yml", FINISHED)


def _driver(st, n, start, trials):
    """A driver ``d{n}`` → its launch ``l{n}`` → *trials* trials, timestamps
    from *start* on."""
    _save(st, f"d{n}", start)
    _save(st, f"l{n}", start + 1, f"d{n}")
    for k in range(trials):
        _save(st, f"t{n}.{k}", start + 2 + k, f"l{n}")


@pytest.fixture
def persisted(tmp_path, monkeypatch):
    """``(storage, index file, runs)``: two old drivers with their trials, a
    single run, and a newest driver whose newest FIRST runs are all trials."""
    st = storage(tmp_path)
    _driver(st, 0, 0, 3)
    _driver(st, 1, 10, 3)
    _save(st, "s", 20)
    _driver(st, 2, 30, TRIALS)
    runs = 3 * 2 + 3 + 3 + 1 + TRIALS
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    monkeypatch.setattr(st, "is_remote", lambda: True, raising=False)
    monkeypatch.setattr(index_module, "FIRST_ROWS", FIRST)
    return st, db, runs


@pytest.fixture
def held_full_read(monkeypatch):
    release, real = threading.Event(), SqliteStore.load_warm
    monkeypatch.setattr(SqliteStore, "load_warm",
                        lambda self, app_name: release.wait(10) and real(self, app_name))
    yield release
    release.set()


def _first_and_full(persisted, held_full_read):
    st, db, _ = persisted
    index = ExperimentIndex(st, APP, cache_path=db)
    first = index.snapshot_now(wait_sec=5)
    held_full_read.set()
    return first, index.snapshot()


def test_the_first_rows_hold_the_newest_runs_ancestors_and_outer_runs(persisted, held_full_read):
    first, full = _first_and_full(persisted, held_full_read)

    got = {r["verstr"] for r in first.rows}
    newest = {r["verstr"] for r in full.rows[-FIRST:]}
    assert newest <= got
    assert {"l2", "d2", "d0", "d1"} <= got
    assert all(r.get("parent") in got for r in first.rows if r.get("parent"))
    for top in ("d0", "d1", "d2"):
        assert any(r.get("parent") == top for r in first.rows)  # reads as an outer run


def test_the_first_rows_are_numbered_and_ordered_as_the_whole_snapshot(persisted, held_full_read):
    first, full = _first_and_full(persisted, held_full_read)

    idx = {r["verstr"]: r["idx"] for r in full.rows}
    assert [r["idx"] for r in first.rows] == sorted(idx[r["verstr"]] for r in first.rows)
    assert all(r["idx"] == idx[r["verstr"]] for r in first.rows)
    assert first.loading == (len(first.rows), persisted[2])


def test_the_first_rows_are_bounded(persisted, held_full_read, monkeypatch):
    monkeypatch.setattr(index_module, "FIRST_ROWS_MAX", FIRST + 2)
    first, _ = _first_and_full(persisted, held_full_read)

    assert len(first.rows) <= FIRST + 2
    got = {r["verstr"] for r in first.rows}
    assert all(r.get("parent") in got for r in first.rows if r.get("parent"))


def test_the_first_rows_read_exp_rows_through_its_indexes(persisted):
    _, db, _ = persisted
    store = SqliteStore(db)
    statements = []
    conn = store.connection()[0]
    conn.set_trace_callback(statements.append)
    try:
        assert store.load_newest(APP, FIRST, 2 * FIRST)
    finally:
        conn.set_trace_callback(None)
    plain = sqlite3.connect(db)
    scans = [
        (sql, detail) for sql in statements if sql.lstrip().upper().startswith(("SELECT", "WITH"))
        and "COUNT(*)" not in sql  # the true total: a covering-index count
        for *_, detail in plain.execute(f"EXPLAIN QUERY PLAN {sql}")
        if detail.startswith("SCAN exp_rows") or "TEMP B-TREE" in detail
    ]
    assert scans == []


def test_a_failed_first_load_stops_serving_the_first_rows(persisted, monkeypatch):
    st, db, _ = persisted

    release = threading.Event()

    def fail(self, app_name):
        release.wait(10)
        raise OSError("disk gone")

    monkeypatch.setattr(SqliteStore, "load_warm", fail)
    index = ExperimentIndex(st, APP, cache_path=db)
    assert index.snapshot_now(wait_sec=5).rows  # the first rows, while it reads
    release.set()
    index.wait_revalidated(10)

    after = index.snapshot_now(wait_sec=0)
    assert after.rows == () and after.loading is not None
