"""What a refresh and a listing read of the persisted index: a remote
refresh's warm records are read on the calling thread before its pool fans
out, and a listing that keeps every run scans each table once."""
import sqlite3
import threading

from vmn_exp.core import index_list, index_list_sql, sqlite_conn, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
R = [f"0.0.1-dev.abc.r{i:02d}" for i in range(10)]


def _ts(second):
    return f"2026-01-01T00:00:{second:02d}Z"


def _seed(st, parents=False):
    for n, verstr in enumerate(R):
        meta = {"verstr": verstr, "timestamp": _ts(10 + n)}
        if parents and n:
            meta["parent"] = R[n - 1]
        st.save(APP, verstr, meta, {})
        st.save_file(APP, verstr, "run_state.yml", FINISHED)


class _Remote(LocalSnapshotStorage):
    def is_remote(self):
        return True


def test_a_remote_refresh_reads_warm_records_on_its_own_thread(tmp_path, monkeypatch):
    st = _Remote(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db, full_sweep_sec=0).refresh()

    readers, parts = [], SqliteStore.records_parts
    monkeypatch.setattr(SqliteStore, "records_parts", lambda self, app, seqs: (
        readers.append(threading.current_thread()), parts(self, app, seqs))[1])
    index = ExperimentIndex(st, APP, cache_path=db, full_sweep_sec=0)
    index.refresh()  # a full listing: every record is refreshed from the pool

    assert readers and set(readers) == {threading.current_thread()}
    assert [r["verstr"] for r in index.snapshot().rows] == R
    index.close()


def _statements(tmp_path, monkeypatch, parents):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st, parents)
    db = str(tmp_path / "idx.sqlite")
    ExperimentIndex(st, APP, cache_path=db).refresh()
    monkeypatch.setattr(index_list_sql, "in_chunks",
                        lambda values: sqlite_conn.in_chunks(values, size=2))
    conn = sqlite3.connect(sqlite_files.live_path(db))
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        total, keep, found, _ = index_list._read(conn, APP, ["archived = 0"], [], None)
    finally:
        conn.close()
    assert total == len(R) and set(keep) == set(R)
    assert [row["verstr"] for row, *_ in found] == R
    return statements


def test_a_listing_keeping_every_run_scans_each_table_once(tmp_path, monkeypatch):
    statements = _statements(tmp_path, monkeypatch, parents=True)
    assert len(statements) <= 6  # count, matching, rows, sides, states, declared
