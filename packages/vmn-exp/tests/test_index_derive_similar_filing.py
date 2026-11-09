"""Plan 33 fix 5: the re-derive writes rows only. The similar-runs documents
are filed afterwards by the filer (:func:`~vmn_exp.core.similar_corpus.file_scope`,
the server's background filing), from what the file already holds: no
documents, or documents the derive marked as behind. A search never answers
from documents that are behind the runs."""
import os
import threading
import time

import pytest
from journal_index_helpers import APP
from similar_fixtures import similar_runs
from similar_seed import seed, verstr
from test_index_upgrade_derived import OLDER, _as_older_derived, _derived, _query, _record
from vmn_exp.core import (index_derive, index_store_schema, similar_corpus, similar_filing,
                          similar_fts)
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.index_point import shared_store
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.similar import SimilarDeadlineExceeded
from vmn_exp.core.similar_corpus import file_scope, needs_filing
from vmn_exp.core.similar_doc import PROFILE_VERSION
from vmn_exp.core.sqlite_conn import connect
from vmn_exp.snapshot import open_storage
from vmn_exp.ui.similar_corpora import SimilarCorpora

pytestmark = pytest.mark.skipif(not similar_fts.fts5_available(),
                                reason="no SQLite FTS5 here")

N = index_derive.CHUNK + 3


def _saved(tmp_path, n=N):
    path = str(tmp_path / "idx.sqlite")
    records = {f"r{i:05d}": _record(f"0.0.1-dev.a.{i}", i) for i in range(n)}
    SqliteStore(path).save(APP, records, set(), records)
    return path


def _older_meta_only(path):
    """The previous DERIVED_VERSION's marks, its derived tables kept as they
    are (an in-place upgrade keeps the documents)."""
    conn = connect(path)
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'schema'", (OLDER,))
    conn.execute("UPDATE exp_index_meta SET v = ? WHERE k = 'records'",
                 (f"{index_store_schema.RECORDS_VERSION}/{OLDER}",))
    conn.close()


def _traced(conn):
    statements = []
    conn.set_trace_callback(statements.append)
    return statements


def _fts_writes(statements):
    return [s for s in statements if "INTO similar_fts" in s]


def test_the_rederive_files_no_documents_and_the_filer_files_them(tmp_path):
    path = _saved(tmp_path)
    expected = _derived(path)
    _as_older_derived(path)  # a new generation: no documents copied
    store = SqliteStore(path)
    statements = _traced(store.connection()[0])
    store.derive(APP)
    store.connection()[0].set_trace_callback(None)

    assert not _fts_writes(statements)
    after = _derived(path)
    assert (after["rows"], after["sides"], after["docs"]) == (expected["rows"],
                                                              expected["sides"], [])
    assert needs_filing(store.connection()[0], APP)
    file_scope(APP, path)
    assert _derived(path)["docs"] == expected["docs"]


def test_documents_an_in_place_upgrade_kept_are_behind_until_refiled(tmp_path):
    path = _saved(tmp_path)
    expected = _derived(path)
    _older_meta_only(path)
    conn = connect(path)
    conn.execute("UPDATE similar_doc SET sig = 'derived by the older version', data = '{}'"
                 " WHERE key = 'r00001'")
    conn.close()
    store = SqliteStore(path)
    store.derive(APP)

    assert needs_filing(store.connection()[0], APP)
    file_scope(APP, path)
    assert _derived(path)["docs"] == expected["docs"]
    assert not needs_filing(store.connection()[0], APP)


def test_refiling_an_unchanged_document_only_restores_its_version(tmp_path):
    path = _saved(tmp_path)
    expected = _derived(path)
    _older_meta_only(path)
    store = shared_store(path)  # the store file_scope searches
    store.derive(APP)
    statements = _traced(store.connection()[0])
    file_scope(APP, path)
    store.connection()[0].set_trace_callback(None)

    assert not _fts_writes(statements)
    assert _derived(path)["docs"] == expected["docs"]
    assert {v for (v,) in _query(path, "SELECT version FROM similar_doc")} == {PROFILE_VERSION}


def test_a_search_of_a_file_still_deriving_derives_it_first(tmp_path):
    path = _saved(tmp_path, 3)
    expected = _derived(path)
    _as_older_derived(path)
    file_scope(APP, path)
    assert not SqliteStore(path).deriving(APP)
    assert _derived(path) == expected


def test_the_filer_writes_in_chunks_and_keeps_a_document_saved_meanwhile(tmp_path,
                                                                         monkeypatch):
    path = _saved(tmp_path, 2 * similar_filing.FILE_CHUNK + 1)
    _as_older_derived(path)
    store = shared_store(path)  # the store file_scope searches
    store.derive(APP)
    newer = dict(_record("0.0.1-dev.a.1", 1))
    newer["meta"] = dict(newer["meta"], note="saved meanwhile")
    real = similar_filing.lean_entries

    def saved_meanwhile(*args):
        entries = real(*args)
        SqliteStore(path).save(APP, {"r00001": newer}, set(), {"r00001": newer})
        return entries

    monkeypatch.setattr(similar_filing, "lean_entries", saved_meanwhile)
    statements = _traced(store.connection()[0])
    file_scope(APP, path)
    store.connection()[0].set_trace_callback(None)

    assert statements.count("BEGIN IMMEDIATE") >= 3
    texts = dict(_query(path, "SELECT d.key, f.text FROM similar_doc d"
                              " JOIN similar_fts f ON f.rowid = d.id"))
    assert "saved meanwhile" in texts["r00001"]
    assert len(texts) == 2 * similar_filing.FILE_CHUNK + 1


class _Refresher:
    def snapshot(self, index, journal=None):
        return index.snapshot()


def _served(tmp_path, notes):
    storage = open_storage(root=str(tmp_path / "store"), area="runs")
    runs = [seed(storage, "app", verstr(n), note=note) for n, note in enumerate(notes, 1)]
    path = str(tmp_path / "index.sqlite")
    index = ExperimentIndex(storage, "app", path, full_sweep_sec=0)
    index.refresh()
    conn = connect(path)
    conn.execute("DELETE FROM similar_fts")  # the documents behind the runs
    conn.execute("DELETE FROM similar_doc")
    conn.close()
    return index, runs


def _held_filer(monkeypatch):
    release, started = threading.Event(), threading.Event()
    real = similar_corpus.file_lean

    def held(*args):
        started.set()
        release.wait(5)
        return real(*args)

    monkeypatch.setattr(similar_corpus, "file_lean", held)
    return release, started


def test_a_server_search_behind_its_documents_answers_not_ready_until_filed(
        tmp_path, monkeypatch):
    index, runs = _served(tmp_path, ["focal loss", "focal smoothing"])
    release, _ = _held_filer(monkeypatch)
    corpora = SimilarCorpora(str(tmp_path / "ui"))
    snapshot = corpora.scoped(_Refresher(), "ws", "app").snapshot(index)
    key = ("ws", "app")

    with pytest.raises(SimilarDeadlineExceeded):
        corpora.scope(key, "app", snapshot, deadline=time.monotonic() + 0.05)
    release.set()
    scope = corpora.scope(key, "app", snapshot)
    found = similar_runs(scope, {"row": None, "text": "focal", "text_only": True})
    assert sorted(i["verstr"] for i in found) == sorted(runs)
    assert not os.path.exists(str(tmp_path / "ui"))


def test_a_refresh_starts_the_servers_filing_before_any_request(tmp_path, monkeypatch):
    index, _ = _served(tmp_path, ["focal loss"])
    release, started = _held_filer(monkeypatch)
    corpora = SimilarCorpora(None)
    snapshot = corpora.scoped(_Refresher(), "ws", "app").snapshot(index)
    corpora.refreshed(index, snapshot)
    assert started.wait(5)
    release.set()
