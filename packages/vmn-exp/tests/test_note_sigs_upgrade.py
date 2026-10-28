"""Plan 28 N7 adds note signatures without a version bump: an index persisted
before it (folds without ``note_sigs``, no ``note_sigs`` side rows) opens as
is — no rebuild, no re-derive, no storage read — and its runs answer
``notes_of`` as None; a run whose fold is extended afterwards gets signatures
for the notes logged after that."""
import json
import sqlite3

import pytest

from journal_index_helpers import APP, Clock, FakeJournal, Spy, make, settle, storage
from test_index_upgrade_derived import _NoReads
from vmn_exp.core import sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.ui.journal_follow import WorkspaceJournal


def _note(st, verstr, text, ts):
    st.append_log_entry(APP, verstr, "w", {"timestamp": ts, "type": "note", "text": text})


def _as_before_n7(db):
    """Strip what N7 persists, as if an older vmn-exp had written *db*."""
    conn = sqlite3.connect(sqlite_files.live_path(db))
    for key, data in conn.execute("SELECT key, data FROM exp_index").fetchall():
        fold = json.loads(data)
        fold.pop("note_sigs", None)
        conn.execute("UPDATE exp_index SET data = ? WHERE key = ?", (json.dumps(fold), key))
    conn.execute("DELETE FROM exp_sides WHERE kind = 'note_sigs'")
    conn.commit()
    conn.close()


def _index(st, db, journal, clock):
    index = ExperimentIndex(st, APP, db, full_sweep_sec=3600)
    ws = WorkspaceJournal(journal.list, SqliteStore(":memory:"), "ws", clock=clock)
    ws.watch(index)
    ws.tick()
    settle(index)
    return index


@pytest.fixture
def before_n7(tmp_path, monkeypatch):
    st = storage(tmp_path)
    verstrs = [make(st, i) for i in range(3)]
    _note(st, verstrs[0], "Received SIGTERM at step 10", "2026-01-01T00:05:00Z")
    Spy(st, monkeypatch)
    db = str(tmp_path / "i.sqlite")
    journal, clock = FakeJournal(), Clock()
    first = _index(st, db, journal, clock)
    assert first.snapshot().notes_of(verstrs[0])  # N7 folded it before the strip
    _as_before_n7(db)
    return st, db, journal, clock, verstrs


def test_an_index_persisted_before_n7_opens_without_rebuild_or_reads(before_n7):
    _, db, journal, clock, verstrs = before_n7
    st = _NoReads()
    index = _index(st, db, journal, clock)
    assert st.calls == []
    assert not SqliteStore(db).deriving(APP)
    snap = index.snapshot()
    assert len(snap.rows) == 3
    assert all(snap.notes_of(v) is None for v in verstrs)


def test_a_run_folded_further_after_the_upgrade_gets_the_new_notes(before_n7):
    st, db, journal, clock, verstrs = before_n7
    _note(st, verstrs[0], "OOMKilled, retry 2", "2026-01-01T00:06:00Z")
    journal.put(clock.t * 1000, verstrs[0])
    index = _index(st, db, journal, clock)
    snap = index.snapshot()
    assert snap.notes_of(verstrs[0]) == {
        "OOMKilled, retry <n>": {"count": 1, "last_at": "2026-01-01T00:06:00Z"}}
    assert snap.notes_of(verstrs[1]) is None
