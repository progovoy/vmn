"""An upgrade that only changes what the index derives from its records
(``DERIVED_VERSION``: the lean rows, side values, similar-runs documents) never
drops the records: the derived tables are re-derived in place from the
persisted records, a chunk per short write transaction, with no storage read,
and the journal mark survives — so the server resumes from the journal."""
import sqlite3
import threading
import time

import pytest

from journal_index_helpers import APP, FINISHED, Clock, FakeJournal, Spy, make, settle, storage
from vmn_exp.core import index_derive, index_store_schema, sqlite_files
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_journal_mark import JournalMark
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_store_schema import ensure_schema
from vmn_exp.core.sqlite_conn import connect
from vmn_exp.ui.journal_follow import WorkspaceJournal

OLDER = f"exp-index-{index_store_schema.DERIVED_VERSION - 1}"
RECORD_TABLES = ("exp_index", "exp_index_state", "exp_index_tombstones", "exp_index_gen")


class _NoReads:
    """A remote store failing every read: an upgraded index must need none."""

    def __init__(self):
        self.calls = []

    def is_remote(self):
        return True

    def __getattr__(self, name):
        if name.startswith("_") or name == "direct_files":  # a remote store has no direct files
            raise AttributeError(name)

        def read(*args, **kwargs):
            self.calls.append(name)
            raise AssertionError(f"storage read: {name}")

        return read


def _first_life(tmp_path, monkeypatch, journal, clock):
    """A journaled index that loaded 6 runs (a parent, metrics) and persisted
    its records and journal mark; its file."""
    st = storage(tmp_path)
    verstrs = [make(st, i) for i in range(6)]
    st.save(APP, verstrs[4], {"verstr": verstrs[4], "timestamp": "2026-01-01T00:00:04Z",
                              "parent": verstrs[1]}, {})
    for step, loss in enumerate((0.9, 0.5)):
        st.append_log_entry(APP, verstrs[2], "w", {
            "timestamp": f"2026-01-01T00:01:0{step}Z", "type": "metrics", "step": step,
            "values": {"loss": loss, "sys_rss_mb": 100.0 + step}})
    Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    ws.watch(index)
    settle(index)
    ws.tick()
    settle(index)
    return db


def _query(db, sql):
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _derived(db):
    """What the derived tables hold (``seq``/doc ids aside)."""
    return {
        "rows": _query(db, "SELECT app, key, verstr, idx, status, parent, root, timestamp,"
                           " name, archived, row FROM exp_rows ORDER BY app, key"),
        "sides": _query(db, "SELECT * FROM exp_sides ORDER BY app, key, kind"),
        "docs": _query(db, "SELECT d.app, d.key, d.verstr, d.rerun, d.cmd, d.version, d.sig,"
                           " d.data, f.text FROM similar_doc d JOIN similar_fts f"
                           " ON f.rowid = d.id ORDER BY d.app, d.key"),
    }


def _records(db):
    return {table: _query(db, f"SELECT * FROM {table} ORDER BY 1, 2") for table in RECORD_TABLES}


def _as_older_derived(db):
    """Make *db* look written by the previous DERIVED_VERSION, its derived
    tables out of date (a reader trusting them would serve garbage)."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'", (OLDER,))
    conn.execute("DELETE FROM exp_rows WHERE key = (SELECT MIN(key) FROM exp_rows)")
    conn.execute("""UPDATE exp_rows SET row = '{"verstr": "stale"}', status = 'stale'""")
    conn.execute("DELETE FROM exp_sides")
    conn.execute("DELETE FROM similar_fts")
    conn.execute("DELETE FROM similar_doc")
    conn.commit()
    conn.close()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal():
    return FakeJournal()


def test_the_versions_split_records_from_what_is_derived_from_them():
    assert (index_store_schema.RECORDS_VERSION, index_store_schema.DERIVED_VERSION) == (18, 19)
    assert index_store_schema.SCHEMA_VERSION == "exp-index-19"


def test_an_older_derived_version_is_rederived_from_the_records_without_storage(
        tmp_path, monkeypatch, journal, clock):
    db = _first_life(tmp_path, monkeypatch, journal, clock)
    expected, records = _derived(db), _records(db)
    mark = JournalMark(SqliteStore(db), APP).load()
    assert mark is not None and len(expected["rows"]) == 6 and expected["docs"]
    _as_older_derived(db)

    st = _NoReads()
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
    ws.watch(index)  # resumes from the mark the upgrade kept
    ws.tick()
    settle(index)

    assert st.calls == []
    assert _derived(db) == expected
    assert _records(db) == records
    assert JournalMark(SqliteStore(db), APP).load() == mark
    assert len(index.snapshot().rows) == 6
    assert not SqliteStore(db).deriving(APP)


def test_opening_an_older_derived_file_drops_nothing_in_one_short_transaction(tmp_path):
    path = str(tmp_path / "idx.sqlite")
    SqliteStore(path).save(APP, {"a": _record("0.0.1-dev.a.0", 1)}, set(), {})
    _as_older_derived(path)
    conn = connect(path)
    statements = []
    conn.set_trace_callback(statements.append)
    ensure_schema(conn)
    assert statements.count("BEGIN IMMEDIATE") == 1
    assert not [s for s in statements if s.lstrip().upper().startswith(("DROP", "DELETE"))]
    assert conn.execute("SELECT COUNT(*) FROM exp_index").fetchone()[0] == 1
    assert SqliteStore(path).deriving(APP)


def _record(verstr, second):
    return {
        "meta_sig": None, "logs": {}, "counts": {}, "rs_sig": None,
        "meta": {"verstr": verstr, "timestamp": f"2026-01-01T{second // 3600:02d}:"
                                                f"{second // 60 % 60:02d}:{second % 60:02d}Z"},
        "fold": fold_log([{"type": "metrics", "timestamp": "2026-01-01T00:00:00Z",
                           "values": {"loss": second / 7}}]),
        "run_state": {"state": "finished", "exit_code": 0},
    }


def test_the_rederive_takes_chunks_and_never_blocks_another_writer(tmp_path):
    n = 3 * index_derive.CHUNK + 7
    path = str(tmp_path / "idx.sqlite")
    records = {f"r{i:05d}": _record(f"0.0.1-dev.a.{i}", i) for i in range(n)}
    SqliteStore(path).save(APP, records, set(), records)
    expected = _derived(path)
    _as_older_derived(path)

    store = SqliteStore(path)
    statements = []
    store.connection()[0].set_trace_callback(statements.append)
    done = threading.Event()
    deriving = threading.Thread(target=lambda: (store.derive(APP), done.set()))
    deriving.start()
    waits = []
    while not done.is_set():
        other = connect(path, busy_timeout_ms=2000)
        started = time.monotonic()
        other.execute("BEGIN IMMEDIATE")  # raises "database is locked" past the bound
        other.execute("COMMIT")
        waits.append(time.monotonic() - started)
        other.close()
    deriving.join()

    assert statements.count("BEGIN IMMEDIATE") >= n // index_derive.CHUNK
    assert waits and max(waits) < 2.0
    assert _derived(path) == expected
    assert not store.deriving(APP)


def test_a_derive_skips_a_record_saved_again_meanwhile(tmp_path, monkeypatch):
    path = str(tmp_path / "idx.sqlite")
    records = {"a": _record("0.0.1-dev.a.1", 1), "b": _record("0.0.1-dev.a.2", 2)}
    SqliteStore(path).save(APP, records, set(), records)
    _as_older_derived(path)
    store = SqliteStore(path)
    newer = dict(records["a"], meta=dict(records["a"]["meta"], name="newer"))
    real = index_derive.decoded_chunk

    def saved_meanwhile(*args):
        chunk = real(*args)
        SqliteStore(path).save(APP, {"a": newer}, set(), {"a": newer})
        return chunk

    monkeypatch.setattr(index_derive, "decoded_chunk", saved_meanwhile)
    store.derive(APP)
    names = dict(_query(path, "SELECT key, name FROM exp_rows"))
    assert names == {"a": "newer", "b": None}


def test_point_reads_answer_none_until_the_rows_are_rederived(tmp_path):
    from vmn_exp.core.index_point import index_path, point_view

    st = storage(tmp_path)
    make(st, 0)
    db = index_path(st, APP)
    ExperimentIndex(st, APP, db).refresh()
    _as_older_derived(db)
    assert point_view(st, APP) is None  # its rows are stale: the caller builds the index
    SqliteStore(db).derive(APP)
    assert point_view(st, APP).resolve("latest")[0] == "0.0.1-dev.abc.r0"
