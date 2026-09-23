"""The run-detail API stays bounded however long a run logs (UI API contract)."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import LocalSnapshotStorage, get_snapshot_storage

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _ts(i):
    return f"2026-01-01T{i // 3600:02d}:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _record(storage, verstr, metadata=None, entries=(), idx=0):
    meta = {"verstr": verstr, "timestamp": _ts(idx)}
    meta.update(metadata or {})
    storage.save(APP, verstr, meta, {})
    for entry in entries:
        storage.append_log_entry(APP, verstr, "w", entry)


def _metric(i, **values):
    return {"timestamp": _ts(i), "type": "metrics", "step": i, "values": values}


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager)), storage


def test_detail_carries_a_bounded_log_tail_and_the_total(ws):
    client, storage = ws
    entries = [{"timestamp": _ts(0), "type": "create"}]
    entries += [_metric(i, loss=1.0 / (i + 1)) for i in range(1, 501)]
    _record(storage, "1.0.0-dev.a", entries=entries)

    detail = client.get(f"{BASE}/1.0.0-dev.a").json()

    assert detail["log_total"] == 501
    assert len(detail["log_tail"]) == 200
    assert detail["log_tail"][-1]["step"] == 500
    # The legacy key is bounded too, so old clients can't pull the whole log.
    assert len(detail["log"]) <= 200


def test_include_log_returns_the_whole_log(ws):
    client, storage = ws
    _record(storage, "1.0.0-dev.a", entries=[_metric(i, loss=0.1) for i in range(300)])

    detail = client.get(f"{BASE}/1.0.0-dev.a?include_log=1").json()

    assert len(detail["log"]) == 300


def test_series_are_downsampled_per_metric_keeping_ends_and_spikes(ws):
    client, storage = ws
    entries = [_metric(i, loss=100.0 if i == 5000 else 1.0) for i in range(10_000)]
    entries += [_metric(i * 1000, val_loss=0.5) for i in range(10)]
    _record(storage, "1.0.0-dev.a", entries=entries)

    detail = client.get(f"{BASE}/1.0.0-dev.a?max_points=100").json()

    loss = detail["series"]["loss"]
    assert len(loss) <= 100
    assert loss[0]["step"] == 0 and loss[-1]["step"] == 9999
    assert any(p["value"] == 100.0 for p in loss), "the spike must survive"
    assert detail["series_total"] == {"loss": 10_000, "val_loss": 10}
    # A sparse metric is not thinned because a dense one is.
    assert len(detail["series"]["val_loss"]) == 10


def test_default_series_cap_is_2000_points(ws):
    client, storage = ws
    _record(storage, "1.0.0-dev.a", entries=[_metric(i, loss=float(i)) for i in range(5000)])

    detail = client.get(f"{BASE}/1.0.0-dev.a").json()

    assert len(detail["series"]["loss"]) <= 2000
    assert detail["series_total"]["loss"] == 5000


def test_patch_presence_comes_from_metadata_flags_not_the_tarball(ws, monkeypatch):
    client, storage = ws
    flags = {
        "has_working_tree_patch": True,
        "has_local_commits_patch": False,
        "has_untracked_files": True,
    }
    _record(storage, "1.0.0-dev.a", metadata=flags)

    def no_patch_load(*args, **kwargs):
        raise AssertionError("detail must not load patches or the tarball")

    monkeypatch.setattr(LocalSnapshotStorage, "load", no_patch_load)
    detail = client.get(f"{BASE}/1.0.0-dev.a").json()

    assert detail["patches"] == {
        "working_tree": True,
        "local_commits": False,
        "untracked_files": True,
    }


def test_status_detail_never_parses_every_metadata_file(ws, monkeypatch):
    client, storage = ws
    _record(storage, "1.0.0-dev.p", idx=0)
    _record(storage, "1.0.0-dev.c1", metadata={"parent": "1.0.0-dev.p"}, idx=1)
    _record(storage, "1.0.0-dev.c2", metadata={"parent": "1.0.0-dev.p"}, idx=2)
    storage.save_file(APP, "1.0.0-dev.c2", "run_state.yml", "state: finished\nexit_code: 1\n")

    def no_full_listing(*args, **kwargs):
        raise AssertionError("detail must not list and parse every metadata file")

    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", no_full_listing)
    for _ in range(2):  # a poll, then the next poll
        status = client.get(f"{BASE}/1.0.0-dev.p").json()["status"]

    assert sorted(status["children"]) == ["1.0.0-dev.c1", "1.0.0-dev.c2"]
    assert status["kind"] == "outer"
    assert status["tree_status"] == "failed"


def test_log_endpoint_pages_oldest_first(ws):
    client, storage = ws
    _record(storage, "1.0.0-dev.a", entries=[_metric(i, loss=0.1) for i in range(120)])

    page = client.get(f"{BASE}/1.0.0-dev.a/log?offset=100&limit=50").json()
    first = client.get(f"{BASE}/1.0.0-dev.a/log?limit=10").json()

    assert page["total"] == 120
    assert [e["step"] for e in page["entries"]] == list(range(100, 120))
    assert [e["step"] for e in first["entries"]] == list(range(10))


def test_log_endpoint_404s_for_an_unknown_run(ws):
    client, _ = ws
    assert client.get(f"{BASE}/1.0.0-dev.nope/log").status_code == 404
