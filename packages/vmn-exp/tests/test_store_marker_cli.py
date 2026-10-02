"""Read-only commands on a missing store say so (plan 14 §2.3); writers mark
the repo-local root."""
import os

import pytest

from exp_helpers import _bootstrap, _exp, _snapshot
from vmn_exp.storage import store_marker
from vmn_exp.storage.areas import local_store_root


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_STORE", "VMN_EXPERIMENT_BUCKET", "VMN_EXPERIMENT_PREFIX",
                "VMN_EXPERIMENT_ENDPOINT_URL", "VMN_EXPERIMENT_DIR", "VMN_EXP_OFFLINE"):
        monkeypatch.delenv(key, raising=False)
    store_marker.forget_checked()


@pytest.mark.parametrize("action", ["list", "show"])
def test_exp_read_on_missing_store(app_layout, capfd, tmp_path, action):
    _bootstrap(app_layout)
    uri = f"file://{tmp_path / 'typo'}"
    capfd.readouterr()
    assert _exp(app_layout.app_name, action=action, extra_args=["--store", uri]) == 1
    out = capfd.readouterr()
    assert f"no vmn store at {uri}" in out.out + out.err
    assert not os.path.exists(tmp_path / "typo")


def test_snapshot_list_on_missing_store(app_layout, capfd, tmp_path):
    _bootstrap(app_layout)
    uri = f"file://{tmp_path / 'typo'}"
    capfd.readouterr()
    assert _snapshot(app_layout.app_name, action="list", store=uri) == 1
    out = capfd.readouterr()
    assert f"no vmn store at {uri}" in out.out + out.err


def test_exp_create_marks_repo_local_root(app_layout):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name) == 0
    root = local_store_root(app_layout.repo_path)
    assert os.path.isfile(os.path.join(root, "store.yml"))


def test_ui_store_workspace_on_missing_store(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path / 'typo'}"
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    resp = TestClient(create_app(manager)).get("/api/v1/workspaces/ws/apps/app/experiments")
    assert resp.status_code == 404
    assert f"no vmn store at {uri}" in resp.text
