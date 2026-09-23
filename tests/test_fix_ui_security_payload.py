"""vmn ui response hygiene: non-finite floats, compression, and index reuse."""
import json
import os

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.ui.server import create_app
from version_stamp.ui.workspaces import WorkspaceManager

LIST = "/api/v1/workspaces/ws/apps/app/experiments"


def _workspace(root, runs):
    """A checkout with experiments ``{verstr: metrics_values_or_None}``."""
    os.makedirs(os.path.join(root, ".git"), exist_ok=True)
    storage = get_snapshot_storage("local", vmn_root_path=root, subdir="experiments")
    for i, (verstr, values) in enumerate(runs.items()):
        storage.save(
            "app", verstr, {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{i}Z"}, {}
        )
        if values is not None:
            storage.append_log_entry(
                "app",
                verstr,
                "h",
                {"timestamp": "2026-01-01T00:00:00Z", "type": "metrics", "values": values},
            )
    return storage


@pytest.fixture
def manager(tmp_path):
    m = WorkspaceManager(str(tmp_path / "data"))
    return m


@pytest.mark.parametrize("use_index", [True, False])
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metric_does_not_break_the_leaderboard(tmp_path, manager, use_index, bad):
    root = str(tmp_path / "ws")
    _workspace(root, {"0.0.1-dev.a": {"acc": 0.9}, "0.0.1-dev.b": {"acc": bad}})
    manager.attach_path("ws", root)
    client = TestClient(create_app(manager, use_index=use_index))

    r = client.get(LIST)
    assert r.status_code == 200
    by_verstr = {row["verstr"]: row for row in r.json()}
    assert by_verstr["0.0.1-dev.a"]["metrics"]["acc"] == 0.9
    assert by_verstr["0.0.1-dev.b"]["metrics"]["acc"] is None

    r = client.get(LIST + "/0.0.1-dev.b")
    assert r.status_code == 200
    assert r.json()["metrics"]["acc"] is None


def test_non_finite_values_nested_in_lists_are_nulled(tmp_path, manager):
    root = str(tmp_path / "ws")
    _workspace(root, {"0.0.1-dev.a": {"loss": float("nan")}})
    manager.attach_path("ws", root)
    client = TestClient(create_app(manager, use_index=False))
    r = client.get(LIST + "/0.0.1-dev.a")
    assert r.status_code == 200
    points = r.json()["series"]["loss"]
    assert points[0]["value"] is None
    # strict JSON: no bare NaN/Infinity tokens on the wire
    json.loads(r.text, parse_constant=lambda c: pytest.fail(f"non-JSON token {c}"))


def test_large_responses_are_gzip_compressed(tmp_path, manager):
    root = str(tmp_path / "ws")
    _workspace(
        root, {f"0.0.1-dev.r{i:03d}": {"loss": i / 100.0} for i in range(60)}
    )
    manager.attach_path("ws", root)
    client = TestClient(create_app(manager, use_index=False))
    r = client.get(LIST, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"
    assert len(r.json()) == 60


def test_readding_a_workspace_name_serves_the_new_path(tmp_path, manager):
    old, new = str(tmp_path / "old"), str(tmp_path / "new")
    _workspace(old, {"0.0.1-dev.old": {"acc": 0.1}})
    _workspace(new, {"0.0.1-dev.new": {"acc": 0.2}})
    manager.attach_path("ws", old)
    client = TestClient(create_app(manager))  # index enabled

    assert [r["verstr"] for r in client.get(LIST).json()] == ["0.0.1-dev.old"]
    assert client.delete("/api/v1/workspaces/ws").status_code == 204
    r = client.post("/api/v1/workspaces", json={"name": "ws", "path": new})
    assert r.status_code == 201
    assert [r["verstr"] for r in client.get(LIST).json()] == ["0.0.1-dev.new"]
