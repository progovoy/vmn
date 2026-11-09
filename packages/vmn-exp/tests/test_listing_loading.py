"""``vmn-exp list`` says it is incomplete from the very snapshot it listed,
not from whichever one the shared index publishes afterwards (plan 33 §2.2):
:func:`~vmn_exp.core.index_list.snapshot_listing` returns its ``loading``."""
import dataclasses
from types import SimpleNamespace

import pytest

import vmn_exp.core.index as experiment_index
import vmn_exp.core.index_list as index_list
from vmn_exp.cli.experiment import experiment_list
from vmn_exp.core.index import ExperimentIndex
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"
RUN = "1.0.0-dev.a"


@pytest.fixture
def storage(tmp_path, monkeypatch):
    st = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    st.save(APP, RUN, {"verstr": RUN, "timestamp": "2026-01-01T00:00:00Z"}, {})
    monkeypatch.setattr(index_list, "list_view", lambda *a, **k: None)  # always a snapshot
    return st


def _listed_snapshots(monkeypatch, listed, published):
    """The listing reads a snapshot *listed* far into its load; by the time
    it is done, the index publishes one *published* far (None: whole)."""
    real = experiment_index.indexed_snapshot
    monkeypatch.setattr(experiment_index, "indexed_snapshot", lambda *a, **k: dataclasses.replace(
        real(*a, **k), loading=listed))
    real_published = ExperimentIndex.published.fget
    monkeypatch.setattr(ExperimentIndex, "published", property(
        lambda self: dataclasses.replace(real_published(self), loading=published)))


def _list(storage):
    return experiment_list(None, None, storage, SimpleNamespace(
        name=APP, query=None, archived=False, last=None, sort=None, top=None, json=False))


def test_snapshot_listing_returns_the_listed_snapshots_loading(storage, monkeypatch):
    _listed_snapshots(monkeypatch, listed=(3, 10), published=None)
    rows, _, any_runs, loading = index_list.snapshot_listing(storage, APP)
    assert [r["verstr"] for r in rows] == [RUN] and any_runs
    assert loading == (3, 10)


def test_a_whole_listed_snapshot_has_no_loading(storage):
    assert index_list.snapshot_listing(storage, APP)[3] is None


def test_vmn_exp_list_says_incomplete_though_the_load_ended_since(storage, monkeypatch, capsys):
    _listed_snapshots(monkeypatch, listed=(120_000, 734_000), published=None)
    assert _list(storage) == 0
    assert "indexing 120k/734k runs — results incomplete" in capsys.readouterr().err


def test_vmn_exp_list_of_a_whole_listing_says_nothing_of_a_later_load(storage, monkeypatch, capsys):
    _listed_snapshots(monkeypatch, listed=None, published=(1, 10))
    assert _list(storage) == 0
    out, err = capsys.readouterr()
    assert RUN in out and "indexing" not in err
