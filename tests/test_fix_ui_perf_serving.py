"""vmn ui serving: artifacts bypass gzip, safe Content-Disposition, static
cache headers, API 404s, constant-time token check, gzip level."""
import os
from urllib.parse import quote

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient

from version_stamp.cli.snapshot import CachedSnapshotStorage, get_snapshot_storage
from version_stamp.ui import server as server_mod
from version_stamp.ui.server import create_app
from version_stamp.ui.workspaces import WorkspaceManager

APP = "app"
V = "1.0.0-dev.a"
ART = f"/api/v1/workspaces/ws/apps/{APP}/experiments/{V}/artifacts"
STATIC = os.path.join(os.path.dirname(server_mod.__file__), "static")


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")
    storage.save(APP, V, {"verstr": V, "timestamp": "t"}, {})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return manager, storage, tmp_path


def test_local_artifacts_are_not_gzipped(ws):
    manager, storage, tmp_path = ws
    src = tmp_path / "model.json"
    src.write_text('{"w": 1}' * 1000)
    storage.save_artifact_file(APP, V, str(src))
    r = TestClient(create_app(manager)).get(
        f"{ART}/model.json", headers={"Accept-Encoding": "gzip"}
    )
    assert r.status_code == 200
    assert "content-encoding" not in r.headers
    assert r.content == src.read_bytes()


@pytest.mark.parametrize("name", ['a"b.bin', "モデル.bin", "naïve;x.bin"])
def test_streamed_artifacts_use_rfc5987_filenames(ws, monkeypatch, name):
    manager, _, _ = ws
    data = b"x" * 5000

    def open_artifact(self, app_name, verstr, filename):
        return iter([data]), len(data)

    monkeypatch.setattr(CachedSnapshotStorage, "open_artifact", open_artifact, raising=False)
    r = TestClient(create_app(manager)).get(
        f"{ART}/{quote(name)}", headers={"Accept-Encoding": "gzip"}
    )
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert f"filename*=UTF-8''{quote(name, safe='')}" in disposition
    assert disposition.count('"') == 2  # one quoted ASCII fallback, nothing broken
    assert "content-encoding" not in r.headers
    assert r.content == data


def test_json_api_responses_are_still_gzipped(ws):
    manager, storage, _ = ws
    for i in range(40):
        storage.save(APP, f"1.0.0-dev.r{i}", {"verstr": f"1.0.0-dev.r{i}", "timestamp": "t"}, {})
    r = TestClient(create_app(manager)).get(
        f"/api/v1/workspaces/ws/apps/{APP}/experiments", headers={"Accept-Encoding": "gzip"}
    )
    assert r.headers.get("content-encoding") == "gzip"


def test_gzip_uses_a_moderate_level(ws):
    manager, _, _ = ws
    app = create_app(manager)
    levels = [m.kwargs.get("compresslevel") for m in app.user_middleware if "GZip" in m.cls.__name__]
    assert levels and all(3 <= level <= 6 for level in levels)


def test_unknown_api_paths_are_json_404s(ws):
    manager, _, _ = ws
    client = TestClient(create_app(manager))
    for path in ("/api/v1/nope", "/api/nope/deeper", "/api"):
        r = client.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json")
        assert "<html" not in r.text.lower()


def _bundle_asset():
    assets = os.path.join(STATIC, "assets")
    if not os.path.isdir(assets) or not os.listdir(assets):
        pytest.skip("web bundle not built")
    return sorted(os.listdir(assets))[0]


def test_hashed_assets_are_cached_forever(ws):
    manager, _, _ = ws
    r = TestClient(create_app(manager)).get(f"/assets/{_bundle_asset()}")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_the_spa_shell_is_revalidated(ws):
    manager, _, _ = ws
    _bundle_asset()
    client = TestClient(create_app(manager))
    for path in ("/", "/workspaces/ws/apps/app", "/index.html"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache", path


def test_token_check_is_constant_time(ws, monkeypatch):
    manager, _, _ = ws
    import hmac

    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    client = TestClient(create_app(manager, token="s3cret"))
    assert client.get("/api/v1/workspaces").status_code == 401
    assert client.get("/api/v1/workspaces", headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.get("/api/v1/workspaces", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert len(calls) >= 2
    assert client.get("/api/v1/workspaces", headers={"Authorization": "Bearer sécret".encode()}).status_code == 401
