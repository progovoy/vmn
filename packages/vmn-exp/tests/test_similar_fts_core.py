"""The FTS5 tables similar runs search (vmn_exp.core.similar_fts): one
document per run, refiled only when what it files changed, its per-column
document frequencies, and a clear error without FTS5."""
import sqlite3

import pytest
from similar_fixtures import changed, run
from vmn_exp.core import similar_fts
from vmn_exp.core.similar_doc import PROFILE_VERSION, build_doc, word


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    similar_fts.ensure_tables(c)
    return c


def _doc(verstr, files=(), note=None, **kw):
    return build_doc(run(verstr, note=note, **kw), changed(files) if files else None)


def _filed(conn, app="app"):
    return sorted(v for (v,) in conn.execute(
        "SELECT verstr FROM similar_fts WHERE app = ?", (app,)))


def test_a_filed_run_has_one_fts_row_and_one_doc(conn):
    similar_fts.file_docs(conn, "app", [("a", _doc("a", ["x.py"])), ("b", _doc("b"))])
    similar_fts.file_docs(conn, "app", [("a", _doc("a", ["y.py"]))])
    assert _filed(conn) == ["a", "b"]
    (files,) = conn.execute("SELECT files FROM similar_fts WHERE verstr = 'a'").fetchone()
    assert files == word("file:y.py")
    assert similar_fts.doc_count(conn, "app") == 2


def test_refiling_an_unchanged_doc_writes_nothing(conn):
    similar_fts.file_docs(conn, "app", [("a", _doc("a", ["x.py"]))])
    before = conn.total_changes
    similar_fts.file_docs(conn, "app", [("a", _doc("a", ["x.py"]))])
    assert conn.total_changes == before


def test_forgotten_keys_leave_both_tables(conn):
    similar_fts.file_docs(conn, "app", [("a", _doc("a")), ("b", _doc("b"))])
    similar_fts.forget(conn, "app", ["a", "missing"])
    assert _filed(conn) == ["b"]
    assert conn.execute("SELECT COUNT(*) FROM similar_doc").fetchone() == (1,)


def test_apps_sharing_a_file_stay_apart(conn):
    similar_fts.file_docs(conn, "one", [("a", _doc("a"))])
    similar_fts.file_docs(conn, "two", [("a", _doc("a", note="other"))])
    similar_fts.forget(conn, "one", ["a"])
    assert _filed(conn, "one") == [] and _filed(conn, "two") == ["a"]


def test_document_frequencies_are_per_column(conn):
    similar_fts.file_docs(conn, "app", [("a", _doc("a", ["x.py"], note="focal loss")),
                                        ("b", _doc("b", ["x.py"], note="focal"))])
    df = similar_fts.document_frequencies(conn, {"text": ["focal", "loss", "absent"],
                                                 "files": [word("file:x.py")]})
    assert df == {("text", "focal"): 2, ("text", "loss"): 1, ("files", word("file:x.py")): 2}


def test_docs_of_another_profile_version_are_counted_stale(conn):
    similar_fts.file_docs(conn, "app", [("a", _doc("a")), ("b", _doc("b"))])
    assert similar_fts.stale_count(conn, "app") == 0
    conn.execute("UPDATE similar_doc SET version = 'old' WHERE key = 'a'")
    assert similar_fts.stale_count(conn, "app") == 1
    assert PROFILE_VERSION != "old"


def test_stored_docs_read_back_with_their_text(conn):
    doc = _doc("a", ["x.py"], note="focal loss")
    similar_fts.file_docs(conn, "app", [("a", doc)])
    [back] = similar_fts.stored_docs(conn, "app", ["a", "missing"]).values()
    assert (back.cols, back.text, back.rerun) == (doc.cols, doc.text, doc.rerun)


def test_without_fts5_similar_runs_say_so(monkeypatch):
    monkeypatch.setattr(similar_fts, "_FTS5", [False])
    with pytest.raises(similar_fts.Fts5Missing, match="SQLite with FTS5"):
        similar_fts.require_fts5()
    c = sqlite3.connect(":memory:")
    similar_fts.create_tables(c)  # the index still works: no similar tables, no error
    assert not similar_fts.has_tables(c)
