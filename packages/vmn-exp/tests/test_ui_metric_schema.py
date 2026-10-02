"""The ui serves the effective metrics schema: conf.yml plus run-declared
goals/hidden flags — even for a store workspace, which has no conf.yml."""
import os

import pytest
import yaml
from exp_helpers import _bootstrap

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.sdk import start_run  # noqa: E402

APP = "app"


def _set_metrics(app_layout, metrics):
    path = os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    with open(path) as f:
        conf = yaml.safe_load(f) or {}
    conf.setdefault("conf", {}).setdefault("experiment", {})["metrics"] = metrics
    with open(path, "w") as f:
        yaml.dump(conf, f)


def _client(app_layout):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def _base(app_layout):
    return f"/api/v1/workspaces/main/apps/{app_layout.app_name}"


def _run(app_layout, acc, **define):
    with start_run(app_layout.app_name) as run:
        if define:
            run.define_metric("acc", **define)
        run.log_metrics({"acc": acc, "grad_norm": 1.0, "lr": 0.1}, step=0)
        return run.id


def test_detail_lists_hidden_metrics_from_run_and_conf(app_layout):
    _bootstrap(app_layout)
    with start_run(app_layout.app_name) as run:
        run.define_metric("grad_*", hidden=True)
        run.log_metrics({"acc": 0.5, "grad_norm": 1.0, "lr": 0.1}, step=0)
        verstr = run.id
    _set_metrics(app_layout, {"lr": {"hidden": True}})
    detail = _client(app_layout).get(f"{_base(app_layout)}/experiments/{verstr}").json()
    assert detail["hidden_metrics"] == ["grad_norm", "lr"]


def test_leaderboard_sorts_on_a_run_declared_goal(app_layout):
    _bootstrap(app_layout)
    low = _run(app_layout, 0.1)
    high = _run(app_layout, 0.9, goal="max")
    client = _client(app_layout)
    rows = client.get(f"{_base(app_layout)}/experiments", params={"sort": "acc"}).json()
    assert [r["verstr"] for r in rows] == [high, low]
    schema = client.get(f"{_base(app_layout)}/metrics-schema").json()
    assert schema == {"acc": {"goal": "max"}}


def test_metrics_schema_endpoint_keeps_the_conf_first(app_layout):
    _bootstrap(app_layout)
    _run(app_layout, 0.9, goal="max", hidden=True)
    _set_metrics(app_layout, {"acc": {"goal": "min"}})
    schema = _client(app_layout).get(f"{_base(app_layout)}/metrics-schema").json()
    assert schema == {"acc": {"goal": "min"}}


@pytest.fixture
def s3_client(tmp_path):
    moto = pytest.importorskip("moto")
    import boto3

    os.environ.setdefault("AWS_ACCESS_KEY_ID", "x")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "x")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="vmn-bucket")
        from vmn_exp.storage.s3 import S3SnapshotStorage
        from vmn_exp.ui.server import create_app
        from vmn_exp.ui.workspaces import WorkspaceManager

        manager = WorkspaceManager(str(tmp_path / "data"))
        manager.add_store("ws", "s3://vmn-bucket/exps")
        yield TestClient(create_app(manager)), S3SnapshotStorage("vmn-bucket", prefix="exps/runs")


def _store_run(storage, verstr, sec, entries):
    ts = f"2026-01-01T00:00:{sec:02d}Z"
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": ts}, {})
    for entry in entries:
        storage.append_log_entry(APP, verstr, "w", dict(entry, timestamp=ts))


def test_metrics_schema_endpoint_merges_declared_goals_for_s3_workspace(s3_client):
    client, storage = s3_client
    _store_run(storage, "1.0.0-dev.low", 1, [
        {"type": "metrics", "values": {"acc": 0.1}}])
    _store_run(storage, "1.0.0-dev.high", 2, [
        {"type": "define_metric", "name": "acc", "goal": "max", "hidden": True},
        {"type": "metrics", "values": {"acc": 0.9}}])
    base = f"/api/v1/workspaces/ws/apps/{APP}"
    assert client.get(f"{base}/metrics-schema").json() == {
        "acc": {"goal": "max", "hidden": True}}
    rows = client.get(f"{base}/experiments", params={"sort": "acc"}).json()
    assert [r["verstr"] for r in rows] == ["1.0.0-dev.high", "1.0.0-dev.low"]
