"""The artifact download route serves nested artifact paths, safely."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

APP = "app"
V = "1.0.0-dev.nested"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}/artifacts"


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    src = tmp_path / "c.txt"
    src.write_bytes(b"nested bytes")
    storage.save_artifact_file(APP, V, str(src), name="artifacts/a/b/c.txt")

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

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
