"""List ordering, caps, cheap app counts and S3 artifacts (UI API contract)."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import (
    LocalSnapshotStorage,
    S3SnapshotStorage,
    get_snapshot_storage,
)
from version_stamp.ui.readers.experiments import sort_rows

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _ts(i):
    return f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _client(tmp_path, use_index=True):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager, use_index=use_index)), storage


def _runs(storage, losses):
    for i, loss in enumerate(losses):
        verstr = f"1.0.0-dev.r{i:04d}"
        storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(i)}, {})
        if loss is not None:
            storage.append_log_entry(
                APP, verstr, "w", {"timestamp": _ts(i), "type": "metrics", "values": {"loss": loss}}
            )


def _losses(resp):
    return [r["metrics"].get("loss") for r in resp.json()["rows"]]


@pytest.mark.parametrize("use_index", [True, False])
def test_order_overrides_the_sort_direction_and_keeps_missing_last(tmp_path, use_index):
    client, storage = _client(tmp_path, use_index)
    _runs(storage, [0.3, None, 0.1, 0.2])

    asc = client.get(f"{BASE}?sort=loss&order=asc&limit=10")
    desc = client.get(f"{BASE}?sort=loss&order=desc&limit=10")

    assert _losses(asc) == [0.1, 0.2, 0.3, None]
    assert _losses(desc) == [0.3, 0.2, 0.1, None]


def test_invalid_order_is_a_400(tmp_path):
    client, storage = _client(tmp_path)
    _runs(storage, [0.1])
    assert client.get(f"{BASE}?order=sideways&limit=5").status_code == 400


@pytest.mark.parametrize("use_index", [True, False])
def test_timestamp_sort_lists_newest_first(tmp_path, use_index):
    client, storage = _client(tmp_path, use_index)
    _runs(storage, [0.1, 0.2, 0.3])

    rows = client.get(f"{BASE}?sort=timestamp&limit=2").json()["rows"]
    oldest = client.get(f"{BASE}?sort=timestamp&order=asc&limit=1").json()["rows"]

    assert [r["verstr"] for r in rows] == ["1.0.0-dev.r0002", "1.0.0-dev.r0001"]
    assert oldest[0]["verstr"] == "1.0.0-dev.r0000"


def test_order_without_a_metric_orders_by_storage_index():
    rows = [{"idx": i, "verstr": str(i), "timestamp": _ts(i), "metrics": {}} for i in range(3)]
    assert [r["idx"] for r in sort_rows(rows, {}, order="desc")] == [2, 1, 0]


def test_limit_is_capped_server_side(tmp_path):
    client, storage = _client(tmp_path, use_index=False)
    _runs(storage, [0.1] * 1005)

    body = client.get(f"{BASE}?limit=5000").json()

    assert body["total"] == 1005
    assert len(body["rows"]) == 1000


def test_app_counts_use_names_only(tmp_path, monkeypatch):
    client, storage = _client(tmp_path)
    _runs(storage, [0.1, 0.2, 0.3])

    def no_full_listing(*args, **kwargs):
        raise AssertionError("counting must not parse every metadata file")

    monkeypatch.setattr(LocalSnapshotStorage, "list_snapshots", no_full_listing)
    apps = {a["name"]: a for a in client.get("/api/v1/workspaces/ws/apps").json()}

    assert apps[APP]["experiments"] == 3


# ---- S3 workspaces -------------------------------------------------------


@pytest.fixture
def s3_client(tmp_path):
    moto = pytest.importorskip("moto")
    import boto3

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        from version_stamp.ui.server import create_app
        from version_stamp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_s3("ws", bucket="vmn-bucket", prefix="exps")
        storage = S3SnapshotStorage("vmn-bucket", prefix="exps")
        yield TestClient(create_app(manager)), storage


def test_s3_artifacts_are_listed_and_downloadable(s3_client, tmp_path):
    client, storage = s3_client
    verstr = "1.0.0-dev.s3run"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(0)}, {})
    model = tmp_path / "model.bin"
    model.write_bytes(b"weights" * 100)
    storage.save_artifact_file(APP, verstr, str(model))

    detail = client.get(f"{BASE}/{verstr}").json()
    got = client.get(f"{BASE}/{verstr}/artifacts/model.bin")
    missing = client.get(f"{BASE}/{verstr}/artifacts/nope.bin")

    assert [a["name"] for a in detail["artifacts"]] == ["model.bin"]
    assert got.status_code == 200 and got.content == b"weights" * 100
    assert missing.status_code == 404
