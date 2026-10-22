"""A store workspace's run diff (the run page's Changes card) answers from
the index snapshot, never reading the runs' logs: a long-stuck outer run's
log is thousands of 30 s segments, and the card took a minute."""
import pytest
from test_ui_diff_summary import _log_define_metric, _log_metrics, _log_params, _save_exp

from vmn_exp.core import index as experiment_index
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.ui.readers import diffs as diff_reader

V1, V2 = "1.0.0-dev.aaa.bbb", "1.0.0-dev.ccc.ddd"


def _first(storage, v):
    _log_define_metric(storage, "myapp", v, "loss", "min")
    _log_params(storage, "myapp", v, {"lr": 0.01, "epochs": 10})
    for loss in (1.0, 0.002, 0.005):
        _log_metrics(storage, "myapp", v, {"loss": loss, "acc": 0.7})


def _second(storage, v):
    _log_define_metric(storage, "myapp", v, "acc", "max")
    _log_params(storage, "myapp", v, {"lr": 0.001, "epochs": 20})
    for loss in (0.001, 0.01):
        _log_metrics(storage, "myapp", v, {"loss": loss, "acc": 0.9})


@pytest.fixture
def storage(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    _save_exp(storage, "myapp", V1)
    _first(storage, V1)
    _save_exp(storage, "myapp", V2, ts="2025-01-02T00:00:00Z")
    _second(storage, V2)
    return storage


def _snap(storage):
    return experiment_index.indexed_snapshot(storage, "myapp", wait=True)


def test_the_snapshot_diff_matches_the_storage_diff(storage):
    expected, err = diff_reader.experiment_diff_from_storage(storage, "myapp", V1, V2)
    assert err is None

    result = diff_reader.experiment_diff_from_snapshot(_snap(storage), V1, V2)

    assert result == expected


def test_the_snapshot_diff_reads_no_log_nor_code(storage, monkeypatch):
    snap = _snap(storage)
    for name in ("load_merged_log", "load_log", "load", "load_record", "load_file"):
        monkeypatch.setattr(storage, name, lambda *a, **k: pytest.fail("read storage"), raising=False)

    assert diff_reader.experiment_diff_from_snapshot(snap, V1, V2)["metrics_delta"]


def test_a_run_the_snapshot_lacks_leaves_it_to_storage(storage):
    assert diff_reader.experiment_diff_from_snapshot(_snap(storage), V1, "1.0.0-dev.not.loaded") is None


def test_the_storage_diff_reads_metadata_not_the_code(storage, monkeypatch):
    monkeypatch.setattr(storage, "load", lambda *a, **k: pytest.fail("loaded patches/code"))
    result, err = diff_reader.experiment_diff_from_storage(storage, "myapp", V1, V2)
    assert err is None and result["metrics_delta"]


def test_the_store_route_answers_from_the_snapshot(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.storage.open import open_storage
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path / 'store'}"
    store = open_storage(store=uri, area="runs")
    _save_exp(store, "myapp", V1)
    _first(store, V1)
    _save_exp(store, "myapp", V2, ts="2025-01-02T00:00:00Z")
    _second(store, V2)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    client = TestClient(create_app(manager))
    monkeypatch.setattr(diff_reader, "experiment_diff_from_storage",
                        lambda *a, **k: pytest.fail("read the runs from storage"))

    resp = client.get(f"/api/v1/workspaces/ws/apps/myapp/experiments-diff?v={V1}&to={V2}")

    assert resp.status_code == 200, resp.text
    # V2 declares no goal for loss: its value is the last (as the storage path says)
    assert resp.json()["metrics_delta"]["loss"] == {"from": 0.002, "to": 0.01, "goal": "min", "param": False}
