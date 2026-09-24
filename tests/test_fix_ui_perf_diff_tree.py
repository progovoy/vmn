"""experiments-diff is cached, gated and capped; the stamp-tree endpoints are
cached by the app's tag list."""
import subprocess

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.ui import tree_cache
from version_stamp.ui.readers import diffs as diff_reader
from version_stamp.ui.readers import tree as tree_reader
from version_stamp.ui.server import create_app
from version_stamp.ui.workspaces import WorkspaceManager

APP = "app"
DIFF = f"/api/v1/workspaces/ws/apps/{APP}/experiments-diff"


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q",
         "--allow-empty", "-m", "init")
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager)), storage, root


def _records(storage, base_commit="abc"):
    for i, name in enumerate(("1.0.0-dev.a", "1.0.0-dev.b")):
        meta = {"verstr": name, "timestamp": f"t{i}", "diff_hash": f"h{i}"}
        if base_commit:
            meta["base_commit"] = base_commit
        storage.save(APP, name, meta, {})


@pytest.fixture
def fake_render(monkeypatch):
    calls = []

    def render(vcs, v1, m1, p1, v2, m2, p2):
        calls.append((v1, v2))
        return render.text, None

    render.text = "diff --git a b\n+x\n"
    monkeypatch.setattr(diff_reader, "render_tree_diff", render)
    diff_reader.DIFF_CACHE.clear()
    return render, calls


def test_diff_results_are_cached(ws, fake_render):
    client, storage, _ = ws
    _, calls = fake_render
    _records(storage)
    params = {"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"}
    first = client.get(DIFF, params=params).json()
    second = client.get(DIFF, params=params).json()
    assert first == second and first["truncated"] is False
    assert len(calls) == 1


def test_a_changed_record_is_diffed_again(ws, fake_render):
    client, storage, _ = ws
    _, calls = fake_render
    _records(storage)
    params = {"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"}
    client.get(DIFF, params=params)
    storage.save(APP, "1.0.0-dev.b", {"verstr": "1.0.0-dev.b", "timestamp": "t1",
                                      "diff_hash": "changed", "base_commit": "abc"}, {})
    client.get(DIFF, params=params)
    assert len(calls) == 2


def test_huge_diffs_are_truncated_with_a_flag(ws, fake_render, monkeypatch):
    client, storage, _ = ws
    render, _ = fake_render
    render.text = "".join(f"+line {i}\n" for i in range(1000))
    monkeypatch.setattr(diff_reader, "MAX_DIFF_BYTES", 100)
    _records(storage)
    body = client.get(DIFF, params={"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"}).json()
    assert body["truncated"] is True
    assert len(body["diff"].encode()) <= 100
    assert body["diff"].endswith("\n")


def test_at_most_two_diffs_run_at_once(ws, fake_render, monkeypatch):
    client, storage, _ = ws
    _records(storage)
    monkeypatch.setattr(diff_reader.DIFF_CACHE, "wait_sec", 0.05)
    gate = diff_reader.DIFF_CACHE.slots
    assert gate.acquire(blocking=False) and gate.acquire(blocking=False)
    try:
        assert not gate.acquire(blocking=False)
        r = client.get(DIFF, params={"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"})
        assert r.status_code == 429
    finally:
        gate.release()
        gate.release()
    r = client.get(DIFF, params={"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"})
    assert r.status_code == 200


def test_records_without_a_base_commit_do_not_500(ws):
    client, storage, _ = ws
    diff_reader.DIFF_CACHE.clear()
    _records(storage, base_commit=None)
    r = client.get(DIFF, params={"v": "1.0.0-dev.a", "to": "1.0.0-dev.b"})
    assert r.status_code == 200
    body = r.json()
    assert body["diff"] is None
    assert "base commit" in body["diff_unavailable"]


@pytest.fixture
def counting_trees(monkeypatch):
    calls = []

    def fake(name):
        def reader(root_path, app_name, **kwargs):
            calls.append((name, app_name, tuple(sorted(kwargs.items()))))
            if name == "deps":
                return {"verstr": kwargs.get("verstr")}, None
            return {"nodes": [], "edges": []} if name == "dag" else []
        return reader

    monkeypatch.setattr(tree_reader, "version_dag", fake("dag"))
    monkeypatch.setattr(tree_reader, "root_topology", fake("root"))
    monkeypatch.setattr(tree_reader, "dep_graph", fake("deps"))
    tree_cache.TREES.clear()
    return calls


@pytest.mark.parametrize("path", ["tree", "tree/root", "deps?v=0.0.1"])
def test_tree_endpoints_are_cached_by_the_tag_list(ws, counting_trees, path):
    client, _, root = ws
    url = f"/api/v1/workspaces/ws/apps/{APP}/{path}"
    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    assert len(counting_trees) == 1
    _git(root, "tag", f"{APP}_0.0.1")
    assert client.get(url).status_code == 200
    assert len(counting_trees) == 2


def test_deps_cache_keys_on_its_arguments(ws, counting_trees):
    client, _, _ = ws
    base = f"/api/v1/workspaces/ws/apps/{APP}/deps"
    assert client.get(base, params={"v": "0.0.1"}).json() == {"verstr": "0.0.1"}
    assert client.get(base, params={"v": "0.0.2"}).json() == {"verstr": "0.0.2"}
    assert len(counting_trees) == 2
