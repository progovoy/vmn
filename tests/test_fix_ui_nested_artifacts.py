"""The artifact download route serves nested artifact paths, safely."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage

APP = "app"
V = "1.0.0-dev.nested"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}/artifacts"


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    src = tmp_path / "c.txt"
    src.write_bytes(b"nested bytes")
    storage.save_artifact_file(APP, V, str(src), name="a/b/c.txt")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager))


def test_a_nested_artifact_downloads(client):
    got = client.get(f"{BASE}/a/b/c.txt")
    assert got.status_code == 200
    assert got.content == b"nested bytes"


def test_a_missing_nested_artifact_is_404(client):
    assert client.get(f"{BASE}/a/b/nope.txt").status_code == 404


@pytest.mark.parametrize("name", ["a/%2E%2E/b", "a%5Cb/c", "a//c.txt", "a/./c.txt"])
def test_unsafe_nested_names_are_refused(client, name):
    assert client.get(f"{BASE}/{name}").status_code in (400, 404)
