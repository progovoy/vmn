import os
import subprocess

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import (
    _experiment,
    _init_app,
    _run_vmn_init,
    _stamp_app,
    extract_dev_verstr,
)


def _make_dirty(app_layout, filename, content):
    app_layout.write_file_commit_and_push("test_repo_0", filename, "initial")
    fpath = os.path.join(app_layout.repo_path, filename)
    with open(fpath, "w") as f:
        f.write(content)
    return fpath


def _seed_experiments(app_layout, capfd, n=3):
    """Stamp the fixture app and create n experiments with a loss metric."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")

    verstrs = []
    losses = [0.5, 0.2, 0.4]
    for i in range(n):
        _make_dirty(app_layout, f"ui_{i}.txt", f"content {i}")
        capfd.readouterr()
        _experiment(
            app_layout.app_name, note=f"run{i}", metrics=[f"loss={losses[i]}"],
        )
        verstrs.append(extract_dev_verstr(capfd.readouterr().out))
    return verstrs


def _client(app_layout, token=None, extra_paths=None):
    """Build a TestClient over a WorkspaceManager with the fixture repo attached."""
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    data_dir = os.path.join(app_layout.base_dir, "ui_data")
    manager = WorkspaceManager(data_dir)
    manager.attach_path("main", app_layout.repo_path)
    for name, path in (extra_paths or {}).items():
        manager.attach_path(name, path)
    app = create_app(manager, token=token)
    return TestClient(app)


def test_ui_workspaces_and_apps(app_layout, capfd):
    _seed_experiments(app_layout, capfd, n=1)
    client = _client(app_layout)

    r = client.get("/api/v1/workspaces")
    assert r.status_code == 200
    names = [w["name"] for w in r.json()]
    assert names == ["main"]

    r = client.get("/api/v1/workspaces/main/apps")
    assert r.status_code == 200
    apps = r.json()
    assert any(a["name"] == app_layout.app_name for a in apps)


def test_ui_leaderboard_matches_cli_sort(app_layout, capfd):
    """API leaderboard order equals `vmn exp list --sort loss` (goal default max)."""
    verstrs = _seed_experiments(app_layout, capfd, n=3)
    client = _client(app_layout)

    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments",
        params={"sort": "loss"},
    )
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 3

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list", sort="loss") == 0
    cli_lines = [
        l for l in capfd.readouterr().out.strip().split("\n") if l.startswith("[")
    ]
    cli_order = [l.split()[1] for l in cli_lines]
    api_order = [row["verstr"] for row in rows]
    assert api_order == cli_order


def test_ui_experiment_detail_and_series(app_layout, capfd):
    verstrs = _seed_experiments(app_layout, capfd, n=1)
    client = _client(app_layout)

    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}"
        f"/experiments/{verstrs[0]}"
    )
    assert r.status_code == 200
    detail = r.json()
    assert detail["metadata"]["verstr"] == verstrs[0]
    assert any(e["type"] == "create" for e in detail["log"])
    assert detail["metrics"]["loss"] == 0.5
    assert detail["series"]["loss"][0]["value"] == 0.5


def test_ui_versions_list(app_layout, capfd):
    _seed_experiments(app_layout, capfd, n=1)
    client = _client(app_layout)

    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/versions"
    )
    assert r.status_code == 200
    versions = r.json()
    assert len(versions) >= 1
    assert versions[-1]["verstr"] == "0.0.1"
    assert versions[-1]["release_mode"] == "patch"


def test_ui_two_workspaces_same_remote_are_independent(app_layout, capfd):
    """Two clones of the same repo are isolated workspaces: an experiment in
    one is invisible in the other."""
    _seed_experiments(app_layout, capfd, n=1)

    second = os.path.join(app_layout.base_dir, "second_clone")
    subprocess.run(
        ["git", "clone", app_layout.test_app_remote, second],
        capture_output=True, check=True,
    )

    client = _client(app_layout, extra_paths={"second": second})

    r1 = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments"
    )
    r2 = client.get(
        f"/api/v1/workspaces/second/apps/{app_layout.app_name}/experiments"
    )
    assert len(r1.json()) == 1
    assert r2.json() == []

    # Both see the stamped version (it lives in shared git tags).
    v2 = client.get(
        f"/api/v1/workspaces/second/apps/{app_layout.app_name}/versions"
    )
    assert v2.json()[-1]["verstr"] == "0.0.1"


def test_ui_registry_persists(app_layout, capfd):
    """The workspace registry survives a manager restart (workspaces.yml)."""
    from version_stamp.ui.workspaces import WorkspaceManager

    _seed_experiments(app_layout, capfd, n=1)
    data_dir = os.path.join(app_layout.base_dir, "ui_data")

    m1 = WorkspaceManager(data_dir)
    m1.attach_path("main", app_layout.repo_path)

    m2 = WorkspaceManager(data_dir)
    assert [w.name for w in m2.list()] == ["main"]
    m2.remove("main")

    m3 = WorkspaceManager(data_dir)
    assert m3.list() == []


def test_ui_token_auth(app_layout, capfd):
    _seed_experiments(app_layout, capfd, n=1)
    client = _client(app_layout, token="s3cret")

    r = client.get("/api/v1/workspaces")
    assert r.status_code == 401

    r = client.get(
        "/api/v1/workspaces", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401

    r = client.get(
        "/api/v1/workspaces", headers={"Authorization": "Bearer s3cret"}
    )
    assert r.status_code == 200


def test_ui_root_app_names_in_urls(app_layout, capfd):
    """Root-app service names (with '/') are addressed by their dashed tag
    form in URLs, matching vmn's tag-name convention."""
    _run_vmn_init()
    _init_app("root_app/svc1")
    _stamp_app("root_app/svc1", "patch")

    client = _client(app_layout)
    r = client.get("/api/v1/workspaces/main/apps")
    names = [a["name"] for a in r.json()]
    assert "root_app/svc1" in names

    r = client.get(
        "/api/v1/workspaces/main/apps/root_app-svc1/versions"
    )
    assert r.status_code == 200
    assert r.json()[-1]["verstr"] == "0.0.1"
