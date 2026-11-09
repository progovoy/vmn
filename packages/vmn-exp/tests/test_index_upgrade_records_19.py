"""Records 20: a fold keeps step restarts, and reads a ``.vmx`` its first and
last write (an older footer kept its step ends). An upgrade from 19 reads no
run again up front: it keeps the file and its rows, and lists the runs whose
fold has compacted metrics logged more than once for a light background
check of their ``.vmx`` footers (:mod:`~vmn_exp.core.vmx_check`) — resumable,
shown as ``checking`` — which folds again only those that need it."""
import json
import sqlite3

import pytest
from journal_index_helpers import APP, Clock, FakeJournal, Spy, make, settle, storage
from vmn_exp.core import index_store_schema, index_vmx_check, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.metric_compact import compact_writer
from vmn_exp.core.metric_stream import MetricWriter
from vmn_exp.ui.journal_follow import WorkspaceJournal

T0 = 1_700_000_000_000_001


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def journal():
    return FakeJournal()


@pytest.fixture(autouse=True)
def _no_background_check(monkeypatch):
    monkeypatch.setattr(index_vmx_check, "BACKGROUND", False)


def _log(st, verstr, sec, entry):
    st.append_log_entry(APP, verstr, "w", {"timestamp": f"2026-01-01T00:01:{sec:02d}Z", **entry})


def _compacted(st, i, steps):
    verstr = make(st, i)
    w = MetricWriter(st, APP, verstr, "w")
    for n, step in enumerate(steps):
        w.add("loss", 1.0 + n, step=step, ts_us=T0 + n)
    w.flush()
    assert compact_writer(st, APP, verstr, "w")
    return verstr


def _runs(st):
    """``(went back, rising, logged, once)``: two compacted runs, one whose
    ``loss`` steps went back; a run logging its points in its JSONL log; one
    logging each metric once."""
    went_back, rising = _compacted(st, 0, [0, 1, 2, 0]), _compacted(st, 1, [0, 1, 2, 3])
    logged, once = make(st, 2), make(st, 3)
    for sec, step in enumerate([0, 1, 2, 0]):
        _log(st, logged, sec, {"type": "metrics", "step": step, "values": {"loss": 1.0 + sec}})
    _log(st, once, 0, {"type": "params", "params": {"lr": 0.1}})
    _log(st, once, 1, {"type": "metrics", "step": 0, "values": {"loss": 0.5, "acc": 0.9}})
    return went_back, rising, logged, once


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


def _listed(spy):
    return set().union(*spy.files) if spy.files else set()


def _upgraded(tmp_path, monkeypatch, journal, clock):
    st = storage(tmp_path)
    runs = _runs(st)
    spy = Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    _life(st, db, journal, clock).close()
    keys = _keys_of(db)
    _as_records_19(db)
    spy.reset()
    return st, db, spy, runs, keys


def test_records_20_read_nothing_again_up_front():
    assert index_store_schema.RECORDS_VERSION == 20
    assert index_store_schema.COPYABLE_RECORDS[19] is None
    older = index_store_schema.COPYABLE_RECORDS[18]
    assert older({"params": {"acc": [3]}, "metrics": {}, "extrema": {"acc": 0.9}})
    assert not older({"params": {}, "metrics": {}, "extrema": {"loss": [0.1, 0.5, 3, 0.9]}})


def test_the_upgrade_lists_compacted_metrics_logged_twice_for_the_check(
        tmp_path, monkeypatch, journal, clock):
    st, db, spy, (went_back, rising, logged, once), keys = _upgraded(
        tmp_path, monkeypatch, journal, clock)
    live = sqlite_files.live_path(db)

    index = _life(st, db, journal, clock)

    assert sqlite_files.live_path(db) == live  # in place
    assert _listed(spy) == set()  # no run read again up front
    assert index.freshness()["checking"] == {"done": 0, "total": 2}
    assert {r["verstr"] for r in index.rows()} == {went_back, rising, logged, once}


def test_the_check_folds_again_only_a_run_that_needs_it(tmp_path, monkeypatch, journal, clock):
    st, db, spy, (went_back, rising, _, _), keys = _upgraded(tmp_path, monkeypatch, journal, clock)
    index = _life(st, db, journal, clock)

    assert index.check_vmx() == 2
    settle(index)

    assert _listed(spy) == {keys[went_back]}
    rows = {r["verstr"]: r for r in index.rows()}
    assert rows[went_back]["step_restarts"] == {"loss": {"from": 2, "to": 0}}
    assert "step_restarts" not in rows[rising]
    assert "checking" not in index.freshness()


def test_the_check_resumes_where_it_stopped(tmp_path, monkeypatch, journal, clock):
    st, db, _, _, _ = _upgraded(tmp_path, monkeypatch, journal, clock)
    index = _life(st, db, journal, clock)
    assert index.check_vmx(limit=1) == 1
    index.close()

    again = _life(st, db, journal, clock)

    assert again.freshness()["checking"] == {"done": 1, "total": 2}
    assert again.check_vmx() == 1


def test_a_refold_the_check_asked_for_survives_a_restart(tmp_path, monkeypatch, journal, clock):
    st, db, spy, (went_back, _, _, _), keys = _upgraded(tmp_path, monkeypatch, journal, clock)
    index = _life(st, db, journal, clock)
    monkeypatch.setattr(index, "_load_listed", lambda *a, **k: None)  # dies before refolding
    index.check_vmx()
    index.close()

    again = _life(st, db, journal, clock)

    rows = {r["verstr"]: r for r in again.rows()}
    assert rows[went_back]["step_restarts"] == {"loss": {"from": 2, "to": 0}}


def test_refreshes_run_the_check_in_the_background(tmp_path, monkeypatch, journal, clock):
    st, db, _, (went_back, _, _, _), _ = _upgraded(tmp_path, monkeypatch, journal, clock)
    monkeypatch.setattr(index_vmx_check, "BACKGROUND", True)
    monkeypatch.setattr(index_vmx_check, "CHECK_EVERY_SEC", 0)

    index = _life(st, db, journal, clock)
    settle(index)

    assert "checking" not in index.freshness()
    assert {r["verstr"]: r for r in index.rows()}[went_back]["step_restarts"]


def test_a_failing_check_never_fails_the_refresh(tmp_path, monkeypatch, journal, clock):
    st, db, _, _, _ = _upgraded(tmp_path, monkeypatch, journal, clock)
    monkeypatch.setattr(index_vmx_check, "BACKGROUND", True)

    def throttled(*args):
        raise OSError("SlowDown")

    monkeypatch.setattr(index_vmx_check, "needs_refold", throttled)
    index = _life(st, db, journal, clock)

    assert index.freshness()["checking"] == {"done": 0, "total": 2}
