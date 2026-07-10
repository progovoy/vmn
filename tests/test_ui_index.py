import os
import subprocess

import pytest

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
    with open(os.path.join(app_layout.repo_path, filename), "w") as f:
        f.write(content)


def _seed(app_layout, capfd, n=2):
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")
    verstrs = []
    for i in range(n):
        _make_dirty(app_layout, f"ix_{i}.txt", f"content {i}")
        capfd.readouterr()
        _experiment(app_layout.app_name, note=f"run{i}", metrics=[f"loss=0.{i + 1}"])
        verstrs.append(extract_dev_verstr(capfd.readouterr().out))
    return verstrs


def _index(app_layout):
    from version_stamp.ui.index import WorkspaceIndex

    db_dir = os.path.join(app_layout.base_dir, "ui_data", "index")
    return WorkspaceIndex(app_layout.repo_path, db_dir=db_dir)


def test_index_experiments_parity(app_layout, capfd):
    """Indexed leaderboard rows equal the direct reader's."""
    from version_stamp.ui.readers import experiments as exp_reader

    _seed(app_layout, capfd, n=3)
    idx = _index(app_layout)

    direct = exp_reader.list_experiments(app_layout.repo_path, app_layout.app_name)
    indexed = idx.list_experiments(app_layout.app_name)
    assert indexed == direct

    direct_sorted = exp_reader.list_experiments(
        app_layout.repo_path, app_layout.app_name, sort="loss"
    )
    indexed_sorted = idx.list_experiments(app_layout.app_name, sort="loss")
    assert indexed_sorted == direct_sorted


def test_index_serves_from_cache(app_layout, capfd, monkeypatch):
    """After a warm read, unchanged data is served without re-reading YAML."""
    _seed(app_layout, capfd, n=2)
    idx = _index(app_layout)

    warm = idx.list_experiments(app_layout.app_name)
    assert len(warm) == 2

    # Poison the expensive fetch path: a cache hit must not call it.
    import version_stamp.ui.index as index_mod

    def _boom(*a, **kw):
        raise AssertionError("cache miss: expensive fetch was called")

    monkeypatch.setattr(index_mod, "_fetch_experiment_rows", _boom)
    cached = idx.list_experiments(app_layout.app_name)
    assert cached == warm


def test_index_invalidates_on_new_experiment(app_layout, capfd):
    _seed(app_layout, capfd, n=1)
    idx = _index(app_layout)
    assert len(idx.list_experiments(app_layout.app_name)) == 1

    _make_dirty(app_layout, "ix_new.txt", "fresh")
    capfd.readouterr()
    _experiment(app_layout.app_name, note="fresh run", metrics=["loss=0.05"])
    new_verstr = extract_dev_verstr(capfd.readouterr().out)

    rows = idx.list_experiments(app_layout.app_name)
    assert len(rows) == 2
    assert any(r["verstr"] == new_verstr for r in rows)


def test_index_versions_parity_and_invalidation(app_layout, capfd):
    from version_stamp.ui.readers import versions as ver_reader

    _seed(app_layout, capfd, n=1)
    idx = _index(app_layout)

    direct = ver_reader.list_versions(app_layout.repo_path, app_layout.app_name)
    assert idx.list_versions(app_layout.app_name) == direct

    # New stamp invalidates the cached tag rows. (Clean the dirty experiment
    # state first — a stamp refuses a dirty tree.)
    subprocess.run(
        ["git", "checkout", "."], cwd=app_layout.repo_path, capture_output=True
    )
    app_layout.write_file_commit_and_push("test_repo_0", "ix_v.txt", "v")
    err, _, _ = _stamp_app(app_layout.app_name, "minor")
    assert err == 0

    rows = idx.list_versions(app_layout.app_name)
    assert rows[-1]["verstr"] == "0.1.0"


def test_index_survives_restart(app_layout, capfd):
    """A fresh WorkspaceIndex over the same db reuses the persisted cache."""
    _seed(app_layout, capfd, n=2)
    idx1 = _index(app_layout)
    warm = idx1.list_experiments(app_layout.app_name)

    idx2 = _index(app_layout)
    assert idx2.list_experiments(app_layout.app_name) == warm


def test_server_uses_index_transparently(app_layout, capfd):
    """API responses are identical with the index enabled (the default)."""
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    verstrs = _seed(app_layout, capfd, n=2)
    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)

    indexed_client = TestClient(create_app(manager))
    direct_client = TestClient(create_app(manager, use_index=False))

    url = f"/api/v1/workspaces/main/apps/{app_layout.app_name}/experiments"
    assert indexed_client.get(url).json() == direct_client.get(url).json()

    vurl = f"/api/v1/workspaces/main/apps/{app_layout.app_name}/versions"
    assert indexed_client.get(vurl).json() == direct_client.get(vurl).json()
