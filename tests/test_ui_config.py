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
    """The /config endpoint returns the parsed conf plus the raw conf.yml text."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("test_repo_0", "d.txt", "x")
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.get(f"/api/v1/workspaces/main/apps/{app_layout.app_name}/config")
    assert r.status_code == 200
    body = r.json()

    repos = body["conf"]["deps"]["../"]
    assert "repo1" in repos and "repo2" in repos
    assert all(info.get("remote") for info in repos.values())

    assert "deps:" in body["text"]
    assert "repo1" in body["text"]


def test_ui_app_config_at_version(app_layout):
    """With ?v=<verstr> the /config endpoint returns the conf.yml recorded at
    that version's tag, not the current working-tree conf."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)

    app_layout.write_conf(params["app_conf_path"], template="[{major}][.{minor}]")
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "x")
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_conf(params["app_conf_path"], template="[{major}]")
    app_layout.write_file_commit_and_push("test_repo_0", "b.txt", "y")
    _stamp_app(app_layout.app_name, "patch")  # 0.0.2

    client = _client(app_layout)
    base = f"/api/v1/workspaces/main/apps/{app_layout.app_name}/config"

    r = client.get(base, params={"v": "0.0.1"})
    assert r.status_code == 200
    body = r.json()
    assert body["conf"]["template"] == "[{major}][.{minor}]"
    assert "[{major}][.{minor}]" in body["text"]

    r = client.get(base, params={"v": "0.0.2"})
    assert r.json()["conf"]["template"] == "[{major}]"

    # Without v: the current working-tree conf.
    r = client.get(base)
    assert r.json()["conf"]["template"] == "[{major}]"


def test_ui_app_config_at_unknown_version_404(app_layout):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "x")
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/config",
        params={"v": "9.9.9"},
    )
    assert r.status_code == 404
