"""Records 20: a fold keeps step restarts, and reads a ``.vmx`` its first and
last write (an older footer kept its step ends). A records-19 fold of a
metric logged more than once may show the value at its highest step and
lacks its restart mark; one logged once (or a run with params only) folds
the same. An upgrade from 19 keeps the file and its rows, reading only those
runs again from storage."""
import json
import sqlite3

import pytest
from journal_index_helpers import APP, Clock, FakeJournal, Spy, make, settle, storage
from vmn_exp.core import index_store_schema, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.journal_follow import WorkspaceJournal


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal():
    return FakeJournal()


def _log(st, verstr, sec, entry):
    st.append_log_entry(APP, verstr, "w", {"timestamp": f"2026-01-01T00:01:{sec:02d}Z", **entry})


def _runs(st):
    """``(curve, once)``: a run whose ``loss`` steps went back, and one
    logging each metric once."""
    curve, once = make(st, 0), make(st, 1)
    for sec, step in enumerate([0, 1, 2, 0]):
        _log(st, curve, sec, {"type": "metrics", "step": step, "values": {"loss": 1.0 + sec}})
    _log(st, once, 0, {"type": "params", "params": {"lr": 0.1}})
    _log(st, once, 1, {"type": "metrics", "step": 0, "values": {"loss": 0.5, "acc": 0.9}})
    return curve, once


def _life(st, db, journal, clock):
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
    ws.watch(index)
    ws.tick()
    settle(index)
    return index


def _as_records_19(db):
    """Mark *db*'s records version 19, every fold without what 20 added."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    (schema,) = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'", (f"19/{schema}",))
    for key, data in conn.execute("SELECT key, data FROM exp_index").fetchall():
        fold = json.loads(data)
        fold.pop("steps", None)
        fold.pop("restarts", None)
        conn.execute("UPDATE exp_index SET data = ? WHERE key = ?", (json.dumps(fold), key))
    conn.commit()
    conn.close()


def _keys_of(db):
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        return {json.loads(head)["meta"]["verstr"]: key
                for key, head in conn.execute("SELECT key, head FROM exp_index")}
    finally:
        conn.close()


def test_records_20_pick_only_metrics_logged_more_than_once():
    assert index_store_schema.RECORDS_VERSION == 20
    assert set(index_store_schema.COPYABLE_RECORDS) == {18, 19}
    stale = index_store_schema.COPYABLE_RECORDS[19]
    assert stale({"params": {}, "metrics": {}, "extrema": {"loss": [0.1, 0.5, 3, 0.9]}})
    assert not stale({"params": {"lr": [0.1]}, "metrics": {}, "extrema": {"loss": 0.5}})
    assert not stale({"params": {"lr": [0.1]}, "metrics": {}})
    older = index_store_schema.COPYABLE_RECORDS[18]
    assert older({"params": {"acc": [3]}, "metrics": {}, "extrema": {"acc": 0.9}})
    assert older({"params": {}, "metrics": {}, "extrema": {"loss": [0.1, 0.5, 3, 0.9]}})
    assert not older({"params": {"lr": [0.1]}, "metrics": {}, "extrema": {"loss": 0.5}})


def test_records_19_upgrade_in_place_reading_only_repeated_metrics_again(
        tmp_path, monkeypatch, journal, clock):
    st = storage(tmp_path)
    curve, once = _runs(st)
    spy = Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    _life(st, db, journal, clock).close()
    keys = _keys_of(db)
    _as_records_19(db)
    live = sqlite_files.live_path(db)

    spy.reset()
    index = _life(st, db, journal, clock)

    assert sqlite_files.live_path(db) == live  # no new generation
    assert set().union(*spy.files) == {keys[curve]}
    rows = {r["verstr"]: r for r in index.rows()}
    assert rows[curve]["step_restarts"] == {"loss": {"from": 2, "to": 0}}
    assert rows[curve]["metrics"]["loss"] == 4.0
    assert rows[once]["metrics"] == {"lr": 0.1, "loss": 0.5, "acc": 0.9}
