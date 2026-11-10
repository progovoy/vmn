"""Plan 34 §4: an upgrade from records 19 deletes nothing, so opening the
file reads no record: it marks the check's list pending, and the check's
steps list its candidates a chunk of records at a time (by rowid) — each
chunk committed with the cursor, so a restart resumes and a step that dies
lists nothing twice."""
import pytest
from test_index_upgrade_records_19 import (  # noqa: F401  (fixtures)
    _no_background_check, _upgraded, clock, journal)
from vmn_exp.core import index_store_schema, index_store_upgrade, index_vmx_check
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.index_vmx_check import VmxCheck
from journal_index_helpers import APP


def _check(db):
    check = VmxCheck(lambda store=SqliteStore(db): store, APP)
    check.load()
    return check


def test_opening_a_records_19_file_reads_no_record(tmp_path, monkeypatch, journal, clock):
    _, db, _, _, _ = _upgraded(tmp_path, monkeypatch, journal, clock)
    scanned = []
    monkeypatch.setattr(index_store_upgrade, "_rows", lambda file: scanned.append(file) or iter(()))

    store = SqliteStore(db)

    assert scanned == []
    assert store.deriving(APP)  # upgraded: its rows left to re-derive
    assert _check(db).state() == {"done": 0, "total": 0}  # listing pending


def test_the_list_builds_a_chunk_at_a_time_and_resumes(tmp_path, monkeypatch, journal, clock):
    _, db, _, (went_back, rising, _, _), keys = _upgraded(tmp_path, monkeypatch, journal, clock)
    SqliteStore(db)
    monkeypatch.setattr(index_vmx_check, "LIST_CHUNK", 1)

    assert _check(db).list_step(limit=1) == 1
    again = _check(db)  # a restart
    while again.list_step(limit=1):
        pass

    assert again.state() == {"done": 0, "total": 2}
    assert _check(db).state() == {"done": 0, "total": 2}
    assert set(again._keys) == {keys[went_back], keys[rising]}


def test_a_step_that_dies_lists_nothing_twice(tmp_path, monkeypatch, journal, clock):
    _, db, _, _, _ = _upgraded(tmp_path, monkeypatch, journal, clock)
    SqliteStore(db)
    monkeypatch.setattr(index_vmx_check, "LIST_CHUNK", 2)
    real, calls = index_store_schema.CHECKED_RECORDS[19], []

    def dies_on_the_third(head, fold):
        calls.append(1)
        if len(calls) == 3:
            raise OSError("killed")
        return real(head, fold)

    monkeypatch.setitem(index_store_schema.CHECKED_RECORDS, 19, dies_on_the_third)
    check = _check(db)
    assert check.list_step(limit=1) == 2
    with pytest.raises(OSError):
        check.list_step(limit=1)

    again = _check(db)
    while again.list_step(limit=1):
        pass
    assert again.state() == {"done": 0, "total": 2}
