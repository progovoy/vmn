"""What one refresh's save costs: each changed run is folded into its lean row
once (the lean tables and the similar-runs filing share it), and the records
and the listing baseline commit in one write transaction."""
import sqlite3

from vmn_exp.core import index_lean_store, similar_filing, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import LocalSnapshotStorage

APP = "app"
FINISHED = "state: finished\nexit_code: 0\n"
R = [f"0.0.1-dev.abc.r{i}" for i in range(4)]


def _ts(second):
    return f"2026-01-01T00:00:{second:02d}Z"


def _seed(st):
    for n, verstr in enumerate(R):
        st.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(10 + n)}, {})
        st.save_file(APP, verstr, "run_state.yml", FINISHED)
        st.append_log_entry(APP, verstr, "w", {"timestamp": _ts(10 + n), "type": "create",
                                               "params": {"lr": 0.1}, "hypothesis": "h"})


def _metric(st, verstr, second, loss):
    st.append_log_entry(APP, verstr, "w", {"timestamp": _ts(second), "type": "metrics",
                                           "values": {"loss": loss}})


def _counting(monkeypatch, module):
    calls = []
    real = module.lean_row

    def counted(idx, meta, fold):
        calls.append(meta["verstr"])
        return real(idx, meta, fold)

    monkeypatch.setattr(module, "lean_row", counted)
    return calls


def test_a_changed_run_is_folded_into_its_lean_row_once_per_save(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(st, APP, cache_path=db)
    index.refresh()
    lean_calls = _counting(monkeypatch, index_lean_store)
    filing_calls = _counting(monkeypatch, similar_filing)

    _metric(st, R[1], 30, 0.5)
    index.refresh()

    assert lean_calls + filing_calls == [R[1]]
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        assert conn.execute("SELECT COUNT(*) FROM similar_doc WHERE app = ?",
                            (APP,)).fetchone()[0] == len(R)
    finally:
        conn.close()
    index.close()


def test_a_refresh_commits_records_and_baseline_in_one_transaction(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "repo"), area="runs")
    _seed(st)
    db = str(tmp_path / "idx.sqlite")
    index = ExperimentIndex(st, APP, cache_path=db)
    index.refresh()
    statements = []
    index._store._conn.set_trace_callback(statements.append)

    _metric(st, R[2], 31, 0.4)
    index.refresh()

    assert sum(s.startswith("BEGIN IMMEDIATE") for s in statements) == 1
    assert any("exp_index_kv" in s for s in statements)  # the baseline was written
    index.close()
