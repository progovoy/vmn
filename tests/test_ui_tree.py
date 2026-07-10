import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import (
    _add_buildmetadata_to_version,
    _configure_2_deps,
    _init_app,
    _release_app,
    _run_vmn_init,
    _stamp_app,
)


def _client(app_layout):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def test_ui_version_dag(app_layout, capfd):
    """DAG nodes for each stamped version, edges from previous_version links."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_file_commit_and_push("test_repo_0", "a.txt", "a")
    _stamp_app(app_layout.app_name, "patch")  # 0.0.2
    app_layout.write_file_commit_and_push("test_repo_0", "b.txt", "b")
    _stamp_app(app_layout.app_name, "minor")  # 0.1.0

    client = _client(app_layout)
    r = client.get(f"/api/v1/workspaces/main/apps/{app_layout.app_name}/tree")
    assert r.status_code == 200
    tree = r.json()

    verstrs = {n["verstr"] for n in tree["nodes"]}
    assert {"0.0.1", "0.0.2", "0.1.0"} <= verstrs

    edges = {(e["from"], e["to"]) for e in tree["edges"]}
    assert ("0.0.1", "0.0.2") in edges
    assert ("0.0.2", "0.1.0") in edges
    assert all(e["from"] != e["to"] for e in tree["edges"])

    by_verstr = {n["verstr"]: n for n in tree["nodes"]}
    assert by_verstr["0.1.0"]["release_mode"] == "minor"
    assert by_verstr["0.1.0"]["branch"]


def test_ui_version_dag_rc_chain(app_layout, capfd):
    """Prerelease nodes carry their base version so chains can collapse."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_file_commit_and_push("test_repo_0", "rc.txt", "1")
    _stamp_app(app_layout.app_name, "patch", prerelease="rc")  # 0.0.2-rc.1
    app_layout.write_file_commit_and_push("test_repo_0", "rc.txt", "2")
    _stamp_app(app_layout.app_name, prerelease="rc")  # 0.0.2-rc.2

    client = _client(app_layout)
    tree = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/tree"
    ).json()

    by_verstr = {n["verstr"]: n for n in tree["nodes"]}
    assert by_verstr["0.0.2-rc.1"]["base"] == "0.0.2"
    assert by_verstr["0.0.2-rc.2"]["base"] == "0.0.2"
    assert by_verstr["0.0.2-rc.1"]["prerelease"] == "rc"
    assert by_verstr["0.0.1"]["base"] == "0.0.1"

    edges = {(e["from"], e["to"]) for e in tree["edges"]}
    assert ("0.0.2-rc.1", "0.0.2-rc.2") in edges


def test_ui_version_dag_release_merges_same_commit(app_layout, capfd):
    """A released version, its source rc, and build metadata share one commit
    and must collapse into a single node (the release), other tags as aliases."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_file_commit_and_push("test_repo_0", "rc.txt", "1")
    _stamp_app(app_layout.app_name, "patch", prerelease="rc")  # 0.0.2-rc.1
    _release_app(app_layout.app_name, "0.0.2-rc.1")  # 0.0.2, same commit
    _add_buildmetadata_to_version(
        app_layout, "build.1", version="0.0.2"
    )  # 0.0.2+build.1, same commit

    client = _client(app_layout)
    tree = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/tree"
    ).json()

    verstrs = [n["verstr"] for n in tree["nodes"]]
    assert "0.0.2" in verstrs
    assert "0.0.2-rc.1" not in verstrs
    assert "0.0.2+build.1" not in verstrs

    node = next(n for n in tree["nodes"] if n["verstr"] == "0.0.2")
    assert set(node["aliases"]) == {"0.0.2-rc.1", "0.0.2+build.1"}
    assert node["release_mode"] == "release"

    edges = {(e["from"], e["to"]) for e in tree["edges"]}
    assert ("0.0.1", "0.0.2") in edges
    assert all(f != t for f, t in edges)
    assert len(tree["edges"]) == len(edges)  # no duplicate edges


def test_ui_root_topology(app_layout, capfd):
    """Root-app topology: services map per root version, with per-step delta."""
    _run_vmn_init()
    _init_app("root_app/svc1")
    _stamp_app("root_app/svc1", "patch")     # root 1: svc1@0.0.1

    app_layout.write_file_commit_and_push("test_repo_0", "s2.txt", "x")
    _init_app("root_app/svc2")
    _stamp_app("root_app/svc2", "patch")     # root 2(+init): svc2 appears

    app_layout.write_file_commit_and_push("test_repo_0", "s1.txt", "y")
    _stamp_app("root_app/svc1", "minor")     # svc1@0.1.0

    client = _client(app_layout)
    r = client.get("/api/v1/workspaces/main/apps/root_app/tree/root")
    assert r.status_code == 200
    topo = r.json()

    assert len(topo) >= 2
    last = topo[-1]
    assert last["services"]["root_app/svc1"] == "0.1.0"
    assert last["services"]["root_app/svc2"] == "0.0.1"
    assert last["latest_service"] == "root_app/svc1"
    assert "root_app/svc1" in last["changed"]

    first = topo[0]
    assert set(first["changed"]) == set(first["services"].keys())


def test_ui_dep_graph(app_layout, capfd):
    """Dependency graph nodes come from the stamped changesets."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("test_repo_0", "d.txt", "x")
    _stamp_app(app_layout.app_name, "patch")

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/deps"
    )
    assert r.status_code == 200
    graph = r.json()

    paths = {n["path"] for n in graph["nodes"]}
    assert "." in paths
    assert any("repo1" in p for p in paths)
    assert any("repo2" in p for p in paths)
    for node in graph["nodes"]:
        assert node["hash"]
    assert graph["verstr"]


def test_ui_dep_drift(app_layout, capfd):
    """Drift view: dep pins compared across two versions."""
    _run_vmn_init()
    err, ver_info, params = _init_app(app_layout.app_name)
    _configure_2_deps(app_layout, params)
    app_layout.write_file_commit_and_push("test_repo_0", "d1.txt", "x")
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    # Advance repo1, then stamp again — its pin moves.
    app_layout.write_file_commit_and_push("repo1", "adv.txt", "z")
    app_layout.write_file_commit_and_push("test_repo_0", "d2.txt", "y")
    _stamp_app(app_layout.app_name, "patch")  # 0.0.2

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/deps",
        params={"v": "0.0.1", "to": "0.0.2"},
    )
    assert r.status_code == 200
    drift = r.json()["drift"]
    moved = {d["path"] for d in drift if d["from"] != d["to"]}
    assert any("repo1" in p for p in moved)
