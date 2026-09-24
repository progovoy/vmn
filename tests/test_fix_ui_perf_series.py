"""Run-detail series selection and the batch series endpoint (UI API contract)."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _ts(i):
    return f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _run(storage, verstr, n=10, keys=("loss", "acc")):
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(0)}, {})
    for i in range(n):
        values = {k: float(i) for k in keys}
        storage.append_log_entry(
            APP, verstr, "w", {"timestamp": _ts(i), "type": "metrics", "step": i, "values": values}
        )


def _client(tmp_path, **opts):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager, **opts)), storage


@pytest.fixture
def ws(tmp_path):
    return _client(tmp_path)


def test_keys_restrict_series_and_totals(ws):
    client, storage = ws
    _run(storage, "1.0.0-dev.a")
    detail = client.get(f"{BASE}/experiments/1.0.0-dev.a?keys=loss,nope").json()
    assert list(detail["series"]) == ["loss"]
    assert detail["series_total"] == {"loss": 10}
    # The latest values are not restricted, only the charts.
    assert set(detail["metrics"]) == {"loss", "acc"}


def test_series_0_omits_series(ws):
    client, storage = ws
    _run(storage, "1.0.0-dev.a")
    detail = client.get(f"{BASE}/experiments/1.0.0-dev.a?series=0").json()
    assert detail["series"] == {}
    assert detail["series_total"] == {}
    assert detail["log_total"] == 10


def test_total_points_per_response_are_capped(ws, monkeypatch):
    from version_stamp.ui.readers import series as series_mod

    monkeypatch.setattr(series_mod, "MAX_TOTAL_POINTS", 1000)
    client, storage = ws
    _run(storage, "1.0.0-dev.a", n=2000, keys=[f"m{i}" for i in range(10)])
    detail = client.get(f"{BASE}/experiments/1.0.0-dev.a?max_points=2000").json()
    total = sum(len(points) for points in detail["series"].values())
    assert total <= 1000
    assert all(len(points) >= 2 for points in detail["series"].values())
    assert detail["series_total"]["m0"] == 2000


def _batch(client, body, **headers):
    return client.post(f"{BASE}/series", json=body, headers=headers)


def test_batch_series_returns_points_per_run(ws):
    client, storage = ws
    _run(storage, "1.0.0-dev.a", n=5)
    _run(storage, "1.0.0-dev.b", n=3, keys=("loss",))
    r = _batch(client, {"verstrs": ["1.0.0-dev.a", "1.0.0-dev.b", "1.0.0-dev.zz"],
                        "keys": ["loss"], "max_points": 100})
    assert r.status_code == 200
    body = r.json()
    assert set(body["series"]) == {"1.0.0-dev.a", "1.0.0-dev.b"}
    assert list(body["series"]["1.0.0-dev.a"]) == ["loss"]
    assert body["series"]["1.0.0-dev.b"]["loss"][2] == {"step": 2, "ts": _ts(2), "value": 2.0}
    assert body["series_total"] == {"1.0.0-dev.a": {"loss": 5}, "1.0.0-dev.b": {"loss": 3}}
    assert body["missing"] == ["1.0.0-dev.zz"]


def test_batch_series_null_keys_means_all_and_thins(ws):
    client, storage = ws
    _run(storage, "1.0.0-dev.a", n=500)
    body = _batch(client, {"verstrs": ["1.0.0-dev.a"], "keys": None, "max_points": 50}).json()
    assert set(body["series"]["1.0.0-dev.a"]) == {"loss", "acc"}
    assert len(body["series"]["1.0.0-dev.a"]["loss"]) <= 50
    assert body["series_total"]["1.0.0-dev.a"]["loss"] == 500


def test_batch_series_rejects_too_many_runs_and_bad_bodies(ws):
    client, _ = ws
    assert _batch(client, {"verstrs": [f"1.0.0-dev.{i}" for i in range(201)]}).status_code == 400
    assert _batch(client, {"verstrs": "1.0.0-dev.a"}).status_code == 400
    assert _batch(client, {"verstrs": ["../x"]}).status_code == 400
    assert _batch(client, {"verstrs": ["a"], "keys": "loss"}).status_code == 400


def test_batch_series_is_allowed_on_a_read_only_server(tmp_path):
    client, storage = _client(tmp_path, read_only=True)
    _run(storage, "1.0.0-dev.a", n=3)
    r = _batch(client, {"verstrs": ["1.0.0-dev.a"]})
    assert r.status_code == 200
    assert r.json()["series_total"]["1.0.0-dev.a"]["loss"] == 3


def test_batch_series_still_passes_the_post_guard(ws):
    client, storage = ws
    _run(storage, "1.0.0-dev.a", n=3)
    r = client.post(f"{BASE}/series", content=b'{"verstrs": []}',
                    headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    r = _batch(client, {"verstrs": ["1.0.0-dev.a"]}, Origin="https://evil.example")
    assert r.status_code == 403
