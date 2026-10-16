"""Searching an index file (vmn_exp.core.similar_corpus.file_scope): one app's
runs of a file several apps share, documents another profile version filed
refiled first, and a rebuilt file searched once its pointer flips."""
import sqlite3

import pytest
from similar_seed import seed, verstr
from vmn_exp.core import similar, sqlite_files
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.similar import similar_runs
from vmn_exp.core.similar_corpus import file_scope
from vmn_exp.snapshot import open_storage


@pytest.fixture
def storage(tmp_path):
    return open_storage(root=str(tmp_path / "store"), area="runs")


def _text(text):
    return {"row": None, "text": text, "text_only": True}


def _index(storage, app, path):
    ExperimentIndex(storage, app, path, full_sweep_sec=0).refresh()


def _found(app, path, text):
    return [i["verstr"] for i in similar_runs(file_scope(app, path), _text(text), top=20)]


def test_an_app_of_a_shared_file_finds_its_own_runs_past_better_ones(storage, tmp_path,
                                                                     monkeypatch):
    path = str(tmp_path / "index.sqlite")
    for n in range(1, 6):
        seed(storage, "other", verstr(n), note="focal loss focal loss")
    mine = seed(storage, "mine", verstr(9), note="focal")
    _index(storage, "other", path)
    _index(storage, "mine", path)
    monkeypatch.setattr(similar, "PAGE", 2)  # the other app's runs fill the first pages
    assert _found("mine", path, "focal loss") == [mine]


def test_documents_of_another_profile_version_are_refiled_first(storage, tmp_path):
    path = str(tmp_path / "index.sqlite")
    focal = seed(storage, "app", verstr(1), note="focal loss")
    _index(storage, "app", path)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("DELETE FROM similar_fts")
    conn.execute("UPDATE similar_doc SET version = 'old'")
    assert _found("app", path, "focal") == [focal]
    assert conn.execute("SELECT version FROM similar_doc").fetchall() != [("old",)]


def test_a_rebuilt_file_is_searched_once_its_pointer_flips(storage, tmp_path):
    path = str(tmp_path / "index.sqlite")
    seed(storage, "app", verstr(1), note="focal loss")
    _index(storage, "app", path)
    assert _found("app", path, "smoothing") == []
    smooth = seed(storage, "app", verstr(2), note="label smoothing")
    fresh = sqlite_files.new_generation(path)
    _index(storage, "app", fresh)
    sqlite_files.flip(path, fresh)
    assert _found("app", path, "smoothing") == [smooth]


def test_a_new_snapshot_never_reuses_a_gone_snapshots_answers():
    # Memoized matches and pages are keyed by the database's identity: a
    # snapshot built where a collected one lived must not inherit its answers.
    import gc

    from similar_fixtures import FakeSnapshot, run

    for n in range(30):
        snap = FakeSnapshot([run(f"r{n}", note="focal loss")])
        assert [i["verstr"] for i in similar_runs(snap, _text("focal"))] == [f"r{n}"]
        del snap
        gc.collect()
