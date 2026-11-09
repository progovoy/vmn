"""Plan 32 F8 changed the fold only for a run with a name that is both a param
and a logged metric (a records-18 fold may hold the param's number over the
metric). An upgrade from records 18 copies every other record over and reads
just those runs again from storage — not the whole store."""
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
    """``(clash, clean)``: a run logging ``acc`` then setting a param ``acc``,
    and one whose param and metric names differ."""
    clash, clean = make(st, 0), make(st, 1)
    _log(st, clash, 0, {"type": "metrics", "values": {"acc": 0.9}})
    _log(st, clash, 1, {"type": "params", "params": {"acc": 3}})
    _log(st, clean, 0, {"type": "params", "params": {"lr": 0.1}})
    _log(st, clean, 1, {"type": "metrics", "values": {"loss": 0.5}})
    return clash, clean


def _life(st, db, journal, clock, journaled):
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    if journaled:
        ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
        ws.watch(index)
        ws.tick()
    settle(index)
    return index


def _as_records_18(db, clash):
    """Mark *db*'s records version 18 and fold *clash* the way 18 did: the
    later param's number over the logged metric."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    (schema,) = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'", (f"18/{schema}",))
    for key, head, data in conn.execute("SELECT key, head, data FROM exp_index").fetchall():
        if json.loads(head)["meta"]["verstr"] == clash:
            fold = json.loads(data)
            fold["metrics"]["acc"][0] = 3
            conn.execute("UPDATE exp_index SET data = ? WHERE key = ?", (json.dumps(fold), key))
    conn.commit()
    conn.close()


def _keys_of(db):
    """``{verstr: record key}`` of *db*'s records."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        return {json.loads(head)["meta"]["verstr"]: key
                for key, head in conn.execute("SELECT key, head FROM exp_index")}
    finally:
        conn.close()


def _listed(spy):
    """The record keys the spied store listed the files of (None: all)."""
    if None in spy.files:
        return None
    return set().union(*spy.files)


@pytest.mark.parametrize("journaled", [True, False])
def test_records_18_are_copied_but_a_param_logged_as_a_metric_is_read_again(
        tmp_path, monkeypatch, journal, clock, journaled):
    st = storage(tmp_path)
    clash, clean = _runs(st)
    spy = Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    _life(st, db, journal, clock, journaled)
    keys = _keys_of(db)
    _as_records_18(db, clash)

    spy.reset()
    index = _life(st, db, journal, clock, journaled)

    assert _listed(spy) == {keys[clash]}  # the clean run was copied, not read
    rows = {r["verstr"]: r for r in index.rows()}
    assert rows[clash]["metrics"]["acc"] == 0.9
    assert rows[clash]["logged_params"] == ["acc"]
    assert rows[clean]["metrics"] == {"lr": 0.1, "loss": 0.5}

    spy.reset()
    _life(st, db, journal, clock, journaled)
    assert not _listed(spy)  # read again once, then trusted like the rest


def test_a_record_left_to_read_again_is_not_copied_with_its_run_state(tmp_path, journal, clock):
    st = storage(tmp_path)
    clash, clean = _runs(st)
    db = str(tmp_path / "i.sqlite")
    _life(st, db, journal, clock, journaled=False)
    keys = _keys_of(db)
    _as_records_18(db, clash)

    store = SqliteStore(db)

    assert set(store.load(APP)) == {keys[clean]}
    conn = sqlite3.connect(sqlite_files.live_path(db))
    assert conn.execute("SELECT key FROM exp_index_state").fetchall() == [(keys[clean],)]


def test_records_18_carry_a_reread_filter():
    assert index_store_schema.RECORDS_VERSION == 20
    assert set(index_store_schema.COPYABLE_RECORDS) == {18, 19}
    stale = index_store_schema.COPYABLE_RECORDS[18]
    assert stale({"params": {"acc": [3]}, "metrics": {"acc": [3]}, "extrema": {"acc": 0.9}})
    assert not stale({"params": {"lr": [0.1]}, "metrics": {"lr": [0.1]}, "extrema": {"loss": 0.5}})


def _as_records(db, version):
    """Mark *db*'s records version *version*."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    (schema,) = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'", (f"{version}/{schema}",))
    conn.commit()
    conn.close()


def test_a_later_upgrade_keeps_the_runs_an_earlier_one_left_to_read_again(
        tmp_path, monkeypatch, journal, clock):
    st = storage(tmp_path)
    clash, clean = _runs(st)
    spy = Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    _life(st, db, journal, clock, journaled=True)
    keys = _keys_of(db)
    _as_records_18(db, clash)
    SqliteStore(db).close()  # upgrade 18 -> 19 lists clash; dies before re-reading it
    _as_records(db, 19)
    monkeypatch.setattr(index_store_schema, "RECORDS_VERSION", 20)
    monkeypatch.setattr(index_store_schema, "COPYABLE_RECORDS",
                        {19: lambda fold: "lr" in fold["params"]})  # picks clean

    spy.reset()
    index = _life(st, db, journal, clock, journaled=True)

    assert _listed(spy) == {keys[clash], keys[clean]}
    assert {r["verstr"] for r in index.rows()} == {clash, clean}
