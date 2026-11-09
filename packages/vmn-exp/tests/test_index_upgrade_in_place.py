"""Plan 33 §2.3: a records version in ``COPYABLE_RECORDS`` is upgraded in
place — no new generation, no copy, no extra disk. The records its predicate
picks are deleted (with their run states and rows) and listed to read again;
the journal mark stays; the kept rows are served, ``loading``, while the
derive rewrites them. An upgrade that dies part way is finished by the next
open."""
import json
import sqlite3
import threading
import time

import pytest
from journal_index_helpers import APP, Clock, FakeJournal, make, settle, storage
from vmn_exp.core import index_derive, index_reread, index_store_upgrade, sqlite_files
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


def _clash(st, i):
    """A run logging ``acc`` then setting a param ``acc`` (records 18 folded it wrong)."""
    verstr = make(st, i)
    _log(st, verstr, 0, {"type": "metrics", "values": {"acc": 0.9}})
    _log(st, verstr, 1, {"type": "params", "params": {"acc": 3}})
    return verstr


def _indexed(tmp_path, journal, clock, clashes=1, cleans=3):
    """``(storage, db, clash verstrs, clean verstrs)`` of a journaled index
    that loaded and persisted them."""
    st = storage(tmp_path)
    clash = [_clash(st, i) for i in range(clashes)]
    clean = [make(st, clashes + i) for i in range(cleans)]
    db = str(tmp_path / "i.sqlite")
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
    ws.watch(index)
    ws.tick()
    settle(index)
    index.close()
    return st, db, clash, clean


def _query(db, sql, *args):
    conn = sqlite3.connect(sqlite_files.live_path(db))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _keys_of(db):
    return {json.loads(head)["meta"]["verstr"]: key
            for key, head in _query(db, "SELECT key, head FROM exp_index")}


def _as_records_18(db, clashes):
    """Mark *db*'s records version 18, each of *clashes* folded the way 18 did."""
    conn = sqlite3.connect(db)
    (schema,) = conn.execute("SELECT v FROM exp_index_meta WHERE k = 'schema'").fetchone()
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'", (f"18/{schema}",))
    for key, head, data in conn.execute("SELECT key, head, data FROM exp_index").fetchall():
        if json.loads(head)["meta"]["verstr"] in clashes:
            fold = json.loads(data)
            fold["metrics"]["acc"][0] = 3
            conn.execute("UPDATE exp_index SET data = ? WHERE key = ?", (json.dumps(fold), key))
    conn.commit()
    conn.close()


def _marks(db):
    return _query(db, "SELECT scope, fingerprint, payload FROM exp_index_kv"
                      " WHERE scope LIKE 'journal-mark:%'")


def test_records_18_upgrade_in_place_with_no_new_generation(tmp_path, journal, clock):
    _, db, clash, _ = _indexed(tmp_path, journal, clock)
    _as_records_18(db, clash)

    store = SqliteStore(db)

    assert store.connection()[1] == db
    assert sqlite_files.live_path(db) == db and not sqlite_files._generations(db)
    assert store.deriving(APP)


def test_the_picked_records_are_deleted_and_listed_to_read_again(tmp_path, journal, clock):
    _, db, clash, clean = _indexed(tmp_path, journal, clock)
    keys = _keys_of(db)
    _as_records_18(db, clash)

    store = SqliteStore(db)

    kept = {keys[v] for v in clean}
    for table in ("exp_index", "exp_index_state", "exp_rows"):
        assert {key for (key,) in _query(db, f"SELECT key FROM {table}")} == kept, table
    assert not _query(db, "SELECT key FROM exp_sides WHERE key = ?", keys[clash[0]])
    assert store.kv_get(index_reread.SCOPE + APP, index_reread.FINGERPRINT) == [keys[clash[0]]]


def test_the_journal_mark_is_kept(tmp_path, journal, clock):
    _, db, clash, _ = _indexed(tmp_path, journal, clock)
    marks = _marks(db)
    assert marks
    _as_records_18(db, clash)

    SqliteStore(db).close()

    assert _marks(db) == marks


def test_an_upgrade_that_died_part_way_is_finished_by_the_next_open(
        tmp_path, monkeypatch, journal, clock):
    _, db, clash, clean = _indexed(tmp_path, journal, clock, clashes=3)
    keys = _keys_of(db)
    _as_records_18(db, clash)
    monkeypatch.setattr(index_store_upgrade, "DELETE_CHUNK", 1)
    real, calls = index_store_upgrade._delete_picked, []

    def dies_after_one(conn, picked):
        calls.append(picked)
        if len(calls) > 1:
            raise sqlite3.OperationalError("killed")
        real(conn, picked)

    monkeypatch.setattr(index_store_upgrade, "_delete_picked", dies_after_one)
    assert SqliteStore(db).connection() is None  # the upgrade failed under it
    monkeypatch.setattr(index_store_upgrade, "_delete_picked", real)

    store = SqliteStore(db)

    assert store.connection()[1] == db and store.deriving(APP)
    assert {key for (key,) in _query(db, "SELECT key FROM exp_index")} == {
        keys[v] for v in clean}
    listed = store.kv_get(index_reread.SCOPE + APP, index_reread.FINGERPRINT)
    assert sorted(listed) == sorted(keys[v] for v in clash)


def test_a_snapshot_mid_derive_serves_the_kept_rows_loading(
        tmp_path, monkeypatch, journal, clock):
    st, db, clash, clean = _indexed(tmp_path, journal, clock)
    _as_records_18(db, clash)
    release, real = threading.Event(), index_derive.derive_chunk

    def held(*args, **kwargs):
        release.wait(20)
        return real(*args, **kwargs)

    monkeypatch.setattr(index_derive, "derive_chunk", held)
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    refresh = threading.Thread(target=index.refresh)
    refresh.start()
    try:
        deadline, snap = time.monotonic() + 10, None
        while time.monotonic() < deadline:
            snap = index.snapshot_now(wait_sec=0.1)
            if snap is not None and snap.rows:
                break
            time.sleep(0.05)
        assert snap is not None and snap.loading is not None
        assert {row["verstr"] for row in snap.rows} == set(clean)
    finally:
        release.set()
        refresh.join(20)
        index.close()
