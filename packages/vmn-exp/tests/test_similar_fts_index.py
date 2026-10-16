"""The experiment index files similar-runs documents in its own save
transaction (plan 24 F2): after a build, a refresh, a removal and a rewind
the FTS table holds one document per current run, as it now is; a refresh
that moves run states only writes none; another process sees them."""
import sqlite3

import pytest
from similar_seed import WRITER, features, finished, seed, verstr
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.snapshot import open_storage

APP = "trainer"


@pytest.fixture
def storage(tmp_path):
    return open_storage(root=str(tmp_path / "store"), area="runs")


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "index.sqlite")


def _docs(path):
    conn = sqlite3.connect(path)
    try:
        return {verstr: (doc_id, text, files) for doc_id, verstr, text, files in conn.execute(
            "SELECT d.id, d.verstr, f.text, f.files FROM similar_doc d"
            " JOIN similar_fts f ON f.rowid = d.id WHERE d.app = ?", (APP,))}
    finally:
        conn.close()


def _refresh(storage, path):
    ExperimentIndex(storage, APP, path, full_sweep_sec=0).refresh()


def test_a_build_files_one_document_per_run(storage, path):
    a = seed(storage, APP, verstr(1), intent={"text": "focal loss"},
             changes=features(["loss.py"]))
    b = seed(storage, APP, verstr(2))
    _refresh(storage, path)
    docs = _docs(path)
    assert set(docs) == {a, b}
    assert "focal loss" in docs[a][1] and docs[a][2]


def test_a_refresh_refiles_what_changed_and_forgets_what_went(storage, path):
    a = seed(storage, APP, verstr(1), intent={"text": "focal loss"})
    b = seed(storage, APP, verstr(2), intent={"text": "label smoothing"})
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    index.refresh()
    storage.append_log_entry(APP, a, WRITER, {"type": "intent", "text": "mixup instead",
                                              "timestamp": "2026-01-02T00:00:00Z",
                                              "source": "user"})
    storage.delete(APP, b)
    c = seed(storage, APP, verstr(3), intent={"text": "cutout"})
    index.refresh()
    docs = _docs(path)
    assert set(docs) == {a, c}
    assert "mixup instead" in docs[a][1] and "focal" not in docs[a][1]


def test_a_rewind_keeps_one_current_document(storage, path):
    a = seed(storage, APP, verstr(1), intent={"text": "focal loss"},
             changes=features(["loss.py"]))
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    index.refresh()
    storage.append_log_entry(APP, a, WRITER, {"type": "metrics", "step": 5, "values": {"x": 1}})
    storage.append_log_entry(APP, a, WRITER, {"type": "rewind", "step": 2})
    index.refresh()
    docs = _docs(path)
    assert list(docs) == [a] and "focal loss" in docs[a][1] and docs[a][2]


def test_a_refresh_moving_run_states_only_refiles_nothing(storage, path):
    a = seed(storage, APP, verstr(1), intent={"text": "focal loss"})
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    index.refresh()
    before = _docs(path)
    finished(storage, APP, a)
    index.refresh()
    assert index.snapshot().status_of(a) == "succeeded"
    assert _docs(path) == before


def test_a_run_state_naming_a_command_refiles_the_run(storage, path):
    a = seed(storage, APP, verstr(1))
    index = ExperimentIndex(storage, APP, path, full_sweep_sec=0)
    index.refresh()
    storage.save_file(APP, a, "run_state.yml",
                      "state: running\npid: 1\nhost: h\ncommand: [python, train.py]\n")
    index.refresh()
    conn = sqlite3.connect(path)
    (entry,) = conn.execute("SELECT entry FROM similar_fts WHERE verstr = ?", (a,)).fetchone()
    assert entry


def test_another_process_sees_a_refresh(storage, path):
    seed(storage, APP, verstr(1))
    _refresh(storage, path)
    reader = sqlite3.connect(path)
    assert reader.execute("SELECT COUNT(*) FROM similar_doc").fetchone() == (1,)
    seed(storage, APP, verstr(2))
    _refresh(storage, path)
    assert reader.execute("SELECT COUNT(*) FROM similar_doc").fetchone() == (2,)
