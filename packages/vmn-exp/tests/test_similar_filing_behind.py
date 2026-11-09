"""Similar-run searches never answer fewer runs without saying so while the
documents are behind the runs (plan 33 fix 5 leftovers):

- a scope opened without filing (the submission hint's) says ``behind``,
  from a check cheap enough for the hint's budget (no counts);
- filing an app holds its file's search lock only per transaction, so other
  apps of the file keep searching;
- the server hands documents left behind again to its background filer and
  answers not-ready (``SimilarDeadlineExceeded``, a 503) meanwhile."""
import threading
import time

import pytest
from journal_index_helpers import APP
from similar_fixtures import similar_runs
from test_index_derive_similar_filing import (_held_filer, _older_meta_only, _Refresher,
                                              _saved, _served, _traced)
from test_index_upgrade_derived import _as_older_derived, _record
from vmn_exp.core import similar_corpus, similar_fts
from vmn_exp.core.index_point import shared_store
from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.similar import SimilarDeadlineExceeded
from vmn_exp.core.similar_corpus import file_scope
from vmn_exp.core.sqlite_conn import connect
from vmn_exp.ui.similar_corpora import SimilarCorpora

pytestmark = pytest.mark.skipif(not similar_fts.fts5_available(),
                                reason="no SQLite FTS5 here")

OTHER = "other"


def _left_to_refile(path):
    """Another process's re-derive left every document to refile."""
    conn = connect(path)
    conn.execute("UPDATE similar_doc SET version = 'refile:' || version")
    conn.close()


def test_a_filed_file_is_not_behind(tmp_path):
    path = _saved(tmp_path, 3)
    assert file_scope(APP, path, repair=False).behind is False


def test_documents_left_to_refile_are_behind_until_filed(tmp_path):
    path = _saved(tmp_path, 3)
    _left_to_refile(path)
    assert file_scope(APP, path, repair=False).behind is True
    assert file_scope(APP, path).behind is False


def test_a_rederive_under_way_is_behind(tmp_path):
    path = _saved(tmp_path, 3)
    _older_meta_only(path)
    assert file_scope(APP, path, repair=False).behind is True


def test_runs_without_any_document_are_behind(tmp_path):
    path = _saved(tmp_path, 3)
    _as_older_derived(path)
    SqliteStore(path).derive(APP)
    assert file_scope(APP, path, repair=False).behind is True


def test_the_behind_check_counts_nothing(tmp_path):
    path = _saved(tmp_path, 3)
    file_scope(APP, path, repair=False)  # opened: the check alone is traced next
    statements = _traced(shared_store(path).connection()[0])
    file_scope(APP, path, repair=False)
    shared_store(path).connection()[0].set_trace_callback(None)
    counts = [s for s in statements if "COUNT(" in s.upper() and "sqlite_master" not in s]
    assert statements and not counts


def _two_apps(tmp_path):
    """An index file of *APP* and *OTHER*, both filed, then *APP*'s
    documents left to refile."""
    path = _saved(tmp_path, 3)
    others = {f"o{i}": _record(f"0.0.1-dev.o.{i}", i) for i in range(2)}
    SqliteStore(path).save(OTHER, others, set(), others)
    file_scope(OTHER, path)
    conn = connect(path)
    conn.execute("UPDATE similar_doc SET version = 'refile:' || version WHERE app = ?", (APP,))
    conn.close()
    return path


def test_filing_an_app_leaves_the_files_other_apps_searching(tmp_path, monkeypatch):
    path = _two_apps(tmp_path)
    release, started = _held_filer(monkeypatch)
    filing = threading.Thread(target=file_scope, args=(APP, path))
    filing.start()
    try:
        assert started.wait(5)
        began = time.monotonic()
        scope = file_scope(OTHER, path)
        assert time.monotonic() - began < 2
        assert scope.lock.acquire(timeout=2)
        scope.lock.release()
    finally:
        release.set()
        filing.join(5)
    assert file_scope(APP, path, repair=False).behind is False


def test_one_filer_files_an_app_while_another_waits_for_it(tmp_path, monkeypatch):
    path = _two_apps(tmp_path)
    calls, real = [], similar_corpus.file_lean

    def counted(*args, **kwargs):
        calls.append(args[1])
        time.sleep(0.2)
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_corpus, "file_lean", counted)
    scopes = []
    threads = [threading.Thread(target=lambda: scopes.append(file_scope(APP, path)))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert calls == [APP]
    assert [s.behind for s in scopes] == [False, False]


def test_documents_left_behind_again_are_filed_in_the_background(tmp_path, monkeypatch):
    index, runs = _served(tmp_path, ["focal loss", "focal smoothing"])
    corpora = SimilarCorpora(None)
    snapshot = corpora.scoped(_Refresher(), "ws", "app").snapshot(index)
    key = ("ws", "app")
    corpora.scope(key, "app", snapshot)  # the first filing, done
    _left_to_refile(index.path)
    release, filers = threading.Event(), []
    real = similar_corpus.file_lean

    def held(*args, **kwargs):
        filers.append(threading.current_thread())
        release.wait(5)
        return real(*args, **kwargs)

    monkeypatch.setattr(similar_corpus, "file_lean", held)
    began = time.monotonic()
    with pytest.raises(SimilarDeadlineExceeded):
        corpora.scope(key, "app", snapshot, deadline=time.monotonic() + 0.05)
    assert time.monotonic() - began < 1
    release.set()
    scope = corpora.scope(key, "app", snapshot, deadline=time.monotonic() + 5)
    assert filers and threading.current_thread() not in filers
    found = similar_runs(scope, {"row": None, "text": "focal", "text_only": True})
    assert sorted(i["verstr"] for i in found) == sorted(runs)
