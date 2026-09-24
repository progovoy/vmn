"""Leaderboard serving: ETag/304 list polls, the no-limit cap, facets, the
cached app list, run detail from the index snapshot, the background refresher
and a persisted S3 index."""
import os
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import (
    LocalSnapshotStorage,
    S3SnapshotStorage,
    get_snapshot_storage,
)
from version_stamp.core import experiment_index
from version_stamp.ui import leaderboard_cache
from version_stamp.ui.readers import experiments as exp_reader

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _ts(i):
    return f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _app(tmp_path, **opts):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return create_app(manager, **opts), storage


@pytest.fixture
def served(tmp_path):
    app, storage = _app(tmp_path)
    return TestClient(app), storage


@pytest.fixture
def background(tmp_path):
    app, storage = _app(tmp_path, background_refresh=True)
    yield TestClient(app), storage
    app.state.refresher.stop()


def _run(storage, i, loss=None, branch="main", parent=None, **params):
    verstr = f"1.0.0-dev.r{i:04d}"
    meta = {"verstr": verstr, "timestamp": _ts(i), "branch": branch}
    if parent:
        meta["parent"] = parent
    storage.save(APP, verstr, meta, {})
    if params:
        storage.append_log_entry(APP, verstr, "w", {"timestamp": _ts(i), "type": "create", "params": params})
    if loss is not None:
        storage.append_log_entry(
            APP, verstr, "w", {"timestamp": _ts(i), "type": "metrics", "values": {"loss": loss}}
        )
    return verstr


def test_an_unchanged_list_poll_is_a_304(served):
    client, storage = served
    for i in range(3):
        _run(storage, i, loss=i / 10)

    first = client.get(f"{BASE}/experiments?limit=10&sort=loss")
    etag = first.headers["etag"]
    again = client.get(f"{BASE}/experiments?limit=10&sort=loss", headers={"If-None-Match": etag})

    assert first.status_code == 200 and first.json()["total"] == 3
    assert again.status_code == 304 and again.content == b""

    _run(storage, 3, loss=0.9)
    changed = client.get(f"{BASE}/experiments?limit=10&sort=loss", headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.json()["total"] == 4
    assert changed.headers["etag"] != etag


def test_a_304_does_no_leaderboard_work(served, monkeypatch):
    client, storage = served
    _run(storage, 0, loss=0.1)
    etag = client.get(f"{BASE}/experiments?limit=10").headers["etag"]

    def boom(*a, **kw):
        raise AssertionError("an unchanged poll re-ran the pipeline")

    monkeypatch.setattr(leaderboard_cache, "sort_rows", boom)
    monkeypatch.setattr(leaderboard_cache, "annotate_tree", boom)
    r = client.get(f"{BASE}/experiments?limit=10", headers={"If-None-Match": etag})
    assert r.status_code == 304


def test_without_limit_the_list_stays_plain_and_is_capped(served):
    client, storage = served
    for i in range(1005):
        verstr = f"1.0.0-dev.r{i:04d}"
        storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(i)}, {})

    rows = client.get(f"{BASE}/experiments").json()

    assert isinstance(rows, list) and len(rows) == 1000


@pytest.mark.parametrize("use_index", [True, False])
def test_facets_list_the_filter_vocabulary(tmp_path, use_index):
    app, storage = _app(tmp_path, use_index=use_index)
    client = TestClient(app)
    _run(storage, 0, loss=0.1, branch="main", lr=0.1)
    _run(storage, 1, branch="feat/x", opt="adam")
    _run(storage, 2, loss=0.3, branch="main")

    facets = client.get(f"{BASE}/experiments-facets")

    assert facets.status_code == 200
    assert facets.json() == {
        "branches": ["feat/x", "main"],
        "metric_keys": ["loss", "lr"],
        "param_keys": ["lr", "opt"],
        "total": 3,
    }


def test_the_app_list_is_cached_per_workspace(served, monkeypatch):
    client, storage = served
    _run(storage, 0)
    calls = []
    real = exp_reader.list_apps

    def counted(root_path):
        calls.append(root_path)
        return real(root_path)

    monkeypatch.setattr(exp_reader, "list_apps", counted)
    first = client.get("/api/v1/workspaces/ws/apps").json()
    second = client.get("/api/v1/workspaces/ws/apps").json()

    assert first == second and first[0]["experiments"] == 1
    assert len(calls) == 1


def test_detail_reads_refs_edges_and_states_from_the_snapshot(background, monkeypatch):
    client, storage = background
    outer = _run(storage, 0, loss=0.5)
    _run(storage, 1, loss=0.2, parent=outer)
    newest = _run(storage, 2, loss=0.1)
    assert client.get(f"{BASE}/experiments?limit=10").json()["total"] == 3

    def no_listing(*a, **kw):
        raise AssertionError("a detail request listed the storage")

    state_reads = []
    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", no_listing)
    monkeypatch.setattr(LocalSnapshotStorage, "list_verstrs", no_listing)
    monkeypatch.setattr(exp_reader, "load_run_state", lambda *a: state_reads.append(a))

    latest = client.get(f"{BASE}/experiments/latest")
    first = client.get(f"{BASE}/experiments/@1")
    log = client.get(f"{BASE}/experiments/@1/log")

    assert latest.status_code == 200 and latest.json()["metadata"]["verstr"] == newest
    assert first.status_code == 200
    assert first.json()["status"]["children"] == ["1.0.0-dev.r0001"]
    assert log.status_code == 200
    assert state_reads == []


def test_background_refresh_shows_new_runs(background):
    client, storage = background
    _run(storage, 0, loss=0.1)
    assert client.get(f"{BASE}/experiments?limit=10").json()["total"] == 1

    _run(storage, 1, loss=0.2)
    deadline = time.monotonic() + 10
    total = 1
    while total < 2 and time.monotonic() < deadline:
        time.sleep(0.1)
        total = client.get(f"{BASE}/experiments?limit=10").json()["total"]
    assert total == 2


@pytest.fixture
def s3_workspace(tmp_path, monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        from version_stamp.ui.server import create_app
        from version_stamp.ui.workspaces import WorkspaceManager

        data_dir = str(tmp_path / "data")
        manager = WorkspaceManager(data_dir)
        manager.add_s3("ws", bucket="vmn-bucket", prefix="persisted")
        yield (lambda: TestClient(create_app(manager))), S3SnapshotStorage(
            "vmn-bucket", prefix="persisted"
        ), data_dir


def test_the_s3_index_persists_under_the_data_dir(s3_workspace, monkeypatch):
    new_client, storage, data_dir = s3_workspace
    for i in range(3):
        _run(storage, i, loss=i / 10)
    assert new_client().get(f"{BASE}/experiments?limit=10").json()["total"] == 3
    assert any(n.endswith(".sqlite") for n in os.listdir(os.path.join(data_dir, "index")))

    # A new server process: no in-memory index, only what the data dir kept.
    monkeypatch.setattr(experiment_index, "_SHARED", {})
    gets = []
    real_get = S3SnapshotStorage._get

    def counted(self, key):
        gets.append(key)
        return real_get(self, key)

    monkeypatch.setattr(S3SnapshotStorage, "_get", counted)
    rows = new_client().get(f"{BASE}/experiments?limit=10").json()["rows"]

    assert sorted(r["metrics"]["loss"] for r in rows) == [0.0, 0.1, 0.2]
    assert gets == []


def test_a_failing_background_listing_keeps_the_last_snapshot(background, monkeypatch, caplog):
    client, storage = background
    _run(storage, 0, loss=0.1)
    assert client.get(f"{BASE}/experiments?limit=10").json()["total"] == 1

    def unreachable(*a, **kw):
        raise OSError("remote listing failed")

    monkeypatch.setattr(LocalSnapshotStorage, "list_files", unreachable)
    monkeypatch.setattr(LocalSnapshotStorage, "list_record_names", unreachable)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not any(
        "refresh failed" in r.getMessage() for r in caplog.records
    ):
        time.sleep(0.05)

    assert any("refresh failed" in r.getMessage() for r in caplog.records)
    r = client.get(f"{BASE}/experiments?limit=10")
    assert r.status_code == 200 and r.json()["total"] == 1


def test_latest_is_found_once_per_snapshot(tmp_path, monkeypatch):
    from version_stamp.core.experiment_index_snapshot import IndexSnapshot
    from version_stamp.ui.experiment_source import ExperimentSource
    from version_stamp.ui.workspaces import Workspace

    rows = [{"verstr": f"1.0.0-dev.r{i}", "timestamp": _ts(i)} for i in range(5)]
    snap = IndexSnapshot.build(APP, 1, rows, {})
    scans = []
    real = IndexSnapshot._latest

    def counted(self, kind):
        scans.append(kind)
        return real(self, kind)

    monkeypatch.setattr(IndexSnapshot, "_latest", counted)
    source = ExperimentSource(str(tmp_path))
    ws = Workspace(name="ws", path=str(tmp_path))

    for _ in range(3):
        assert source.detail_options(ws, snap)["resolve"]("latest") == ("1.0.0-dev.r4", None)
    assert source.detail_options(ws, snap)["resolve"]("@2") == ("1.0.0-dev.r1", None)
    assert len(scans) == 1
