"""The ui derives stuck on both clocks: a run_state.yml the store saw written
recently is live however stale its writer's heartbeat timestamp is."""
import os

import pytest
from test_fix_exp_status_store_clock import _running, _write_run

from version_stamp.cli.snapshot_storage_local import LocalSnapshotStorage

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

API = "/api/v1/workspaces/main/apps"


def _client(app_layout, use_index=True):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager, use_index=use_index))


def _seed(app_layout):
    _write_run(app_layout, "0.0.1", _running(600))  # writer clock 10 min behind
    _write_run(app_layout, "0.0.2", _running(600), store_age_sec=900)  # dead
    return {"0.0.1": "running", "0.0.2": "stuck"}


def _list(client, app_layout):
    rows = client.get(f"{API}/{app_layout.app_name}/experiments").json()
    return {r["verstr"]: r["status"] for r in rows}


def _detail_status(client, app_layout, verstr):
    detail = client.get(f"{API}/{app_layout.app_name}/experiments/{verstr}").json()
    return detail["status"]["status"]


@pytest.mark.parametrize("use_index", [True, False])
def test_list_trusts_a_fresh_store_write(app_layout, use_index):
    expected = _seed(app_layout)
    assert _list(_client(app_layout, use_index), app_layout) == expected


@pytest.mark.parametrize("use_index", [True, False])
def test_detail_trusts_a_fresh_store_write(app_layout, use_index):
    expected = _seed(app_layout)
    client = _client(app_layout, use_index)
    for verstr, status in expected.items():
        assert _detail_status(client, app_layout, verstr) == status


def test_leaderboard_rederive_keeps_using_the_store_time(app_layout, monkeypatch):
    """A later time bucket re-derives live rows: still with the store time."""
    from version_stamp.ui import leaderboard_cache

    expected = _seed(app_layout)
    client = _client(app_layout)
    assert _list(client, app_layout) == expected
    monkeypatch.setattr(leaderboard_cache.LeaderboardCache, "_bucket", lambda self: -1)
    assert _list(client, app_layout) == expected


def test_detail_uses_the_snapshot_store_time_with_a_refresher():
    from version_stamp.core.experiment_index_snapshot import IndexSnapshot
    from version_stamp.ui.experiment_source import ExperimentSource

    observed = object()
    snap = IndexSnapshot.build("app", 1, [{"verstr": "v"}], {"v": {}},
                               observed_at={"v": observed})
    source = ExperimentSource("/nonexistent", refresher=object())
    options = source.detail_options(None, snap)
    assert options["read_observed_at"](None, "app", "v") is observed


@pytest.fixture
def no_store_mtime(monkeypatch):
    real = LocalSnapshotStorage._files_in

    def files_in(path):
        return {name: (sig[0], None) for name, sig in real(path).items()}

    monkeypatch.setattr(LocalSnapshotStorage, "_files_in", staticmethod(files_in))


@pytest.mark.parametrize("use_index", [True, False])
def test_unknown_store_time_falls_back_to_the_heartbeat(
    app_layout, no_store_mtime, use_index
):
    _seed(app_layout)
    client = _client(app_layout, use_index)
    assert _list(client, app_layout) == {"0.0.1": "stuck", "0.0.2": "stuck"}
    assert _detail_status(client, app_layout, "0.0.1") == "stuck"
