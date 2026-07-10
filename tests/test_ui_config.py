import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import (
    _configure_2_deps,
    _init_app,
    _run_vmn_init,
    _stamp_app,
)


def _client(app_layout):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def test_read_app_conf_missing_is_empty():
    from version_stamp.ui.readers.config import read_app_conf

    assert read_app_conf("/nonexistent", "nope") == {}


def test_ui_app_config_endpoint(app_layout, capfd):
    """The /config endpoint returns the raw app conf; deps is a key like any other."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("test_repo_0", "d.txt", "x")
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.get(f"/api/v1/workspaces/main/apps/{app_layout.app_name}/config")
    assert r.status_code == 200
    conf = r.json()

    repos = conf["deps"]["../"]
    assert "repo1" in repos and "repo2" in repos
    assert all(info.get("remote") for info in repos.values())
