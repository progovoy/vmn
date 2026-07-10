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


def test_app_config_flattens_deps():
    """The reader flattens the nested deps config into a flat list."""
    from version_stamp.ui.readers.config import app_config
    # Point at a made-up path — with no conf.yml the reader returns empties.
    cfg = app_config("/nonexistent", "nope")
    assert cfg == {"conf": {}, "deps": []}


def test_ui_app_config_endpoint(app_layout, capfd):
    """The /config endpoint returns the app conf and a flattened deps list."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("test_repo_0", "d.txt", "x")
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.get(f"/api/v1/workspaces/main/apps/{app_layout.app_name}/config")
    assert r.status_code == 200
    cfg = r.json()

    assert "conf" in cfg
    dep_paths = {d["path"] for d in cfg["deps"]}
    assert any("repo1" in p for p in dep_paths)
    assert any("repo2" in p for p in dep_paths)
    assert all(d.get("remote") for d in cfg["deps"])
