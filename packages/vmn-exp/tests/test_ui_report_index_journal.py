"""A store workspace served with the background refresher feeds its report
index from the workspace's journal follower: new reports and comments show
through the API while only the journal thread lists the store's journal."""
import threading
import time

import pytest

pytest.importorskip("fastapi")
moto = pytest.importorskip("moto")
import boto3  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.storage import s3_base  # noqa: E402
from vmn_exp.storage.s3 import S3SnapshotStorage  # noqa: E402

APP = "app"
WS = "/api/v1/workspaces/ws"


@pytest.fixture
def journal_listers(monkeypatch):
    """Names of the threads that listed the store's journal."""
    threads = []
    real = s3_base.boto3_client

    def note(params, **_):
        if "/journal/" in params.get("Prefix", ""):
            threads.append(threading.current_thread().name)

    def counted(*args, **kwargs):
        client = real(*args, **kwargs)
        client.meta.events.register("before-parameter-build.s3.ListObjectsV2", note)
        return client

    monkeypatch.setattr(s3_base, "boto3_client", counted)
    return threads


@pytest.fixture
def client(tmp_path, monkeypatch, journal_listers):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        storage = S3SnapshotStorage("vmn-bucket", prefix="st/runs")
        storage.save(APP, "0.0.1", {"verstr": "0.0.1", "timestamp": "2026-01-01T00:00:00Z"}, {})
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("ws", "s3://vmn-bucket/st")
        app = create_app(manager, background_refresh=True)
        yield TestClient(app)
        app.state.refresher.stop()


def _poll(client, predicate, timeout=15.0):
    """Poll the experiments list (the dashboard's idle request) until *predicate*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        client.get(f"{WS}/apps/{APP}/experiments?top=1&limit=50")
        if predicate():
            return True
        time.sleep(0.3)
    return predicate()


def _comments_of(client):
    rows = client.get(f"{WS}/apps/{APP}/experiments").json()
    return {r["verstr"]: r.get("comments") for r in rows}


def _rids(client):
    return [r["rid"] for r in client.get(f"{WS}/reports").json()["reports"]]


def test_reports_and_comments_show_without_the_report_index_listing_the_journal(
        client, journal_listers):
    assert _poll(client, lambda: "vmn-ui-journal" in journal_listers)
    _poll(client, lambda: False, timeout=2.5)  # the follower feeds the index by now
    journal_listers.clear()
    r = client.post(f"{WS}/comments", json={"target": f"run:{APP}:0.0.1", "text": "hi"})
    assert r.status_code == 201, r.text
    assert _poll(client, lambda: (_comments_of(client)["0.0.1"] or {}).get("total") == 1)
    rid = client.post(f"{WS}/reports", json={"title": "T", "body": ""}).json()["rid"]
    assert _poll(client, lambda: _rids(client) == [rid])
    assert journal_listers and set(journal_listers) == {"vmn-ui-journal"}
