"""Where ``vmn-exp ui`` searches similar runs (vmn_exp.ui.similar_corpora): an
app whose index persists in a SQLite file searches that file; any other (a
Postgres-cached store, ``--no-index``) a host-local database kept in step
with its snapshots — on each refresh (the refresher's ``on_index_refresh``)
and, when a request finds it behind, in the background while the request
waits up to its deadline."""
import os
import threading

import pytest
from similar_fixtures import FakeSnapshot, run
from similar_seed import seed, verstr
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.core.similar import SimilarDeadlineExceeded, similar_runs
from vmn_exp.snapshot import open_storage
from vmn_exp.ui import similar_corpora
from vmn_exp.ui.similar_corpora import SimilarCorpora

KEY = ("ws", "app")


def _text_target(text):
    return {"row": None, "text": text, "text_only": True}


def _snap(*notes):
    return FakeSnapshot([run(f"r{i}", note=note) for i, note in enumerate(notes)])


class _Refresher:
    def snapshot(self, index, journal=None):
        return index.snapshot()


def test_an_index_persisted_in_a_file_is_searched_in_it(tmp_path):
    storage = open_storage(root=str(tmp_path / "store"), area="runs")
    focal = seed(storage, "app", verstr(1), note="focal loss")
    path = str(tmp_path / "index.sqlite")
    index = ExperimentIndex(storage, "app", path, full_sweep_sec=0)
    corpora = SimilarCorpora(str(tmp_path / "ui"))
    snapshot = corpora.scoped(_Refresher(), *KEY).snapshot(index.refresh())

    scope = corpora.scope(KEY, "app", snapshot)
    assert scope.app == "app" and scope.label == KEY
    assert [i["verstr"] for i in similar_runs(scope, _text_target("focal"))] == [focal]
    assert not os.path.exists(str(tmp_path / "ui"))  # nothing filed twice


def test_another_index_is_kept_in_a_host_local_database(tmp_path):
    corpora = SimilarCorpora(str(tmp_path))
    scope = corpora.scope(KEY, "app", _snap("focal loss", "label smoothing"))
    assert [i["verstr"] for i in similar_runs(scope, _text_target("smoothing"))] == ["r1"]
    assert os.listdir(tmp_path)  # a file of its own
    later = corpora.scope(KEY, "app", _snap("focal loss", "label smoothing", "more smoothing"))
    assert sorted(i["verstr"] for i in similar_runs(later, _text_target("smoothing"))) == [
        "r1", "r2"]


def test_without_a_data_dir_the_database_is_in_memory():
    scope = SimilarCorpora(None).scope(KEY, "app", _snap("focal loss"))
    assert [i["verstr"] for i in similar_runs(scope, _text_target("focal"))] == ["r0"]


def test_a_refresh_syncs_the_database_before_any_request(tmp_path, monkeypatch):
    corpora = SimilarCorpora(None)
    index = object()
    corpora.note(index, KEY, "app")
    snapshot = _snap("focal loss")
    corpora.refreshed(index, snapshot)
    monkeypatch.setattr(similar_corpora, "_start", lambda *a: pytest.fail("synced again"))
    corpora.scope(KEY, "app", snapshot)


def test_a_request_past_its_deadline_leaves_the_sync_running(monkeypatch):
    corpora, release = SimilarCorpora(None), threading.Event()
    real = similar_corpora.SnapshotFiler.sync

    def slow(filer, snapshot):
        release.wait(5)
        return real(filer, snapshot)

    monkeypatch.setattr(similar_corpora.SnapshotFiler, "sync", slow)
    snapshot = _snap("focal loss")
    with pytest.raises(SimilarDeadlineExceeded):
        corpora.scope(KEY, "app", snapshot, deadline=0.0)
    release.set()
    scope = corpora.scope(KEY, "app", snapshot, deadline=None)
    assert [i["verstr"] for i in similar_runs(scope, _text_target("focal"))] == ["r0"]
