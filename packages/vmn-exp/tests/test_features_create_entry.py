"""``create_run(features=...)``: a run's ``features`` entry is written right
after its ``create`` entry, in the same batch; without one only the create
entry is written."""
import pytest
from vmn_exp.core import writer as experiment_writer
from vmn_exp.core.features import FEATURES_VERSION, build_features_entry
from vmn_exp.core.writer import create_run


class _Scalar:
    """A numpy-like scalar: the create entry's params must still be unwrapped."""

    def item(self):
        return 0.5


class _BatchStorage:
    """Duck-typed storage recording each log write (batch or single)."""

    def __init__(self):
        self.saved = {}
        self.writes = []

    def save(self, app_name, verstr, metadata, patches):
        self.saved[verstr] = (metadata, patches)

    def exists(self, app_name, verstr):
        return verstr in self.saved

    def list_snapshots(self, app_name):
        return [meta for meta, _ in self.saved.values()]

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        self.writes.append((verstr, writer_id, [entry]))

    def append_log_entries(self, app_name, verstr, writer_id, entries):
        self.writes.append((verstr, writer_id, list(entries)))
        return True


@pytest.fixture(autouse=True)
def _writer(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "gpu-07")
    experiment_writer._WRITER_ID = None


def _features():
    return build_features_entry(
        "capture", author={"writer": "gpu-07", "git_user_email": "a@x.io", "source": "git"},
        changed={"files": ["loss.py"], "symbols": ["loss.py::focal_loss"]},
        commits=["try focal loss"],
    )


def test_the_features_entry_follows_the_create_entry_in_one_write():
    storage = _BatchStorage()
    verstr = create_run(storage, "app", "0.0.1-dev.aaa.bbb", {}, {}, note="n",
                        create_data={"params": {"lr": _Scalar()}}, features=_features())

    [(written_verstr, writer, entries)] = storage.writes
    assert (written_verstr, writer) == (verstr, "gpu-07")
    create, features = entries
    assert create["type"] == "create" and create["note"] == "n"
    assert create["params"] == {"lr": 0.5}
    assert features["type"] == "features"
    assert features["features_version"] == FEATURES_VERSION
    assert features["source"] == "capture"
    assert features["changed"] == {"files": ["loss.py"], "symbols": ["loss.py::focal_loss"]}
    assert features["commits"] == ["try focal loss"]
    assert features["author"]["git_user_email"] == "a@x.io"
    assert features["timestamp"] == create["timestamp"]


def test_without_features_only_the_create_entry_is_written():
    storage = _BatchStorage()
    create_run(storage, "app", "0.0.1-dev.aaa.bbb", {}, {}, note="n")

    [(_, _, entries)] = storage.writes
    assert [e["type"] for e in entries] == ["create"]


def test_the_given_features_entry_is_not_modified():
    storage = _BatchStorage()
    features = _features()
    before = dict(features)
    create_run(storage, "app", "0.0.1-dev.aaa.bbb", {}, {}, features=features)
    assert features == before
