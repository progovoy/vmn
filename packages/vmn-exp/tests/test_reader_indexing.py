"""While the app's index snapshot is still loading, the readers never present
the partial runs as the whole app (plan 33 §2.2): ``list_runs`` (and every
reader of the same rows) warns :class:`IndexingWarning`, ``vmn-exp list``
prints ``indexing 120k/734k runs — results incomplete`` on stderr."""
import dataclasses
import warnings
from types import SimpleNamespace

import pytest

import vmn_exp.core.index as experiment_index
import vmn_exp.core.index_list as index_list
from vmn_exp.cli.experiment import experiment_list
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.sdk import reader
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
RUN = "1.0.0-dev.a"
INCOMPLETE = "indexing 120k/734k runs — results incomplete"


@pytest.fixture
def storage(tmp_path):
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    st.save(APP, RUN, {"verstr": RUN, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _loading_snapshots(monkeypatch, state):
    real = experiment_index.indexed_snapshot
    monkeypatch.setattr(experiment_index, "indexed_snapshot", lambda *a, **k: dataclasses.replace(
        real(*a, **k), loading=state))


def test_list_runs_warns_while_the_index_loads(storage, monkeypatch):
    _loading_snapshots(monkeypatch, (120_000, 734_000))
    with pytest.warns(reader.IndexingWarning, match=INCOMPLETE):
        rows = reader.list_runs(APP, storage=storage)
    assert [r["verstr"] for r in rows] == [RUN]


def test_list_runs_names_what_it_loaded_before_the_total_is_known(storage, monkeypatch):
    _loading_snapshots(monkeypatch, (950, None))
    with pytest.warns(reader.IndexingWarning, match="indexing 950 runs — results incomplete"):
        reader.list_runs(APP, storage=storage)


def test_a_loaded_index_lists_without_a_warning(storage):
    with warnings.catch_warnings():
        warnings.simplefilter("error", reader.IndexingWarning)
        assert [r["verstr"] for r in reader.list_runs(APP, storage=storage)] == [RUN]


def _list(storage):
    return experiment_list(None, None, storage, SimpleNamespace(
        name=APP, query=None, archived=False, last=None, sort=None, top=None, json=False))


def test_vmn_exp_list_says_on_stderr_its_listing_is_incomplete(storage, monkeypatch, capsys):
    monkeypatch.setattr(index_list, "list_view", lambda *a, **k: None)  # e.g. rows re-deriving
    published = ExperimentIndex.published.fget
    monkeypatch.setattr(ExperimentIndex, "published", property(
        lambda self: dataclasses.replace(published(self), loading=(120_000, 734_000))))
    assert _list(storage) == 0
    out, err = capsys.readouterr()
    assert INCOMPLETE in err and INCOMPLETE not in out
    assert RUN in out


def test_vmn_exp_list_of_a_loaded_index_says_nothing_on_stderr(storage, capsys):
    assert _list(storage) == 0
    out, err = capsys.readouterr()
    assert RUN in out and "indexing" not in err
