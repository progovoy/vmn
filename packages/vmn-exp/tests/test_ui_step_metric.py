"""Series endpoints keyed by another metric (``x=``) and declared step metrics."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from vmn_exp.snapshot import open_storage
from vmn_exp.storage.areas import local_store_root

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
RUN = "1.0.0-dev.a"


def _ts(i):
    return f"2026-01-01T00:{i // 60 % 60:02d}:{i % 60:02d}.{i:06d}Z"


def _run(storage, verstr=RUN, n=10, define=None):
    storage.save(APP, verstr, {"verstr": verstr, "timestamp": _ts(0)}, {})
    if define:
        storage.append_log_entry(APP, verstr, "w", dict(
            {"timestamp": _ts(0), "type": "define_metric"}, **define
        ))
    for i in range(n):
        values = {"loss": float(i), "acc": float(i)}
        if i % 2 == 0:
            values["epoch"] = i / 2
        storage.append_log_entry(
            APP, verstr, "w",
            {"timestamp": _ts(i + 1), "type": "metrics", "step": i, "values": values},
        )


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = open_storage(root=local_store_root(str(root)), area="runs")

    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager)), storage, root


def test_detail_x_param_joins_every_series_on_the_x_metric(ws):
    client, storage, _ = ws
    _run(storage)
    detail = client.get(f"{BASE}/experiments/{RUN}?x=epoch").json()
    assert set(detail["series"]) == {"loss", "acc"}
    assert detail["series"]["loss"][1] == {"step": 2, "ts": _ts(3), "value": 2.0, "x": 1.0}
    assert detail["series_total"]["loss"] == 5  # odd steps carry no epoch


def test_detail_reports_declared_step_metrics(ws):
    client, storage, _ = ws
    _run(storage, define={"name": "l*", "step_metric": "epoch"})
    detail = client.get(f"{BASE}/experiments/{RUN}").json()
    assert detail["step_metrics"] == {"loss": "epoch"}
    assert "x" not in detail["series"]["loss"][0]


def test_conf_schema_declares_step_metrics_too(ws):
    client, storage, root = ws
    conf = root / ".vmn" / APP / "conf.yml"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("conf:\n  experiment:\n    metrics:\n      acc:\n        goal: max\n"
                    "        step_metric: epoch\n")
    _run(storage)
    detail = client.get(f"{BASE}/experiments/{RUN}").json()
    assert detail["step_metrics"] == {"acc": "epoch"}


def test_joined_series_are_downsampled(ws):
    client, storage, _ = ws
    _run(storage, n=400)
    detail = client.get(f"{BASE}/experiments/{RUN}?x=epoch&max_points=20").json()
    assert 2 < len(detail["series"]["loss"]) <= 20
    assert detail["series_total"]["loss"] == 200
    assert all("x" in p for p in detail["series"]["loss"])


def test_batch_x_string_and_per_metric_map(ws):
    client, storage, _ = ws
    _run(storage, define={"name": "acc", "step_metric": "epoch"})
    body = client.post(f"{BASE}/series", json={"verstrs": [RUN], "x": "epoch"}).json()
    assert set(body["series"][RUN]) == {"loss", "acc"}
    assert all("x" in p for p in body["series"][RUN]["loss"])
    assert body["step_metrics"] == {RUN: {"acc": "epoch"}}

    body = client.post(f"{BASE}/series", json={
        "verstrs": [RUN], "keys": ["loss", "acc"], "x": {"acc": "epoch"},
    }).json()
    assert len(body["series"][RUN]["loss"]) == 10 and "x" not in body["series"][RUN]["loss"][0]
    assert body["series"][RUN]["acc"][0]["x"] == 0.0
    assert body["series_total"][RUN] == {"loss": 10, "acc": 5}


def test_batch_rejects_a_bad_x(ws):
    client, storage, _ = ws
    _run(storage)
    for x in (3, ["epoch"], {"acc": 1}):
        r = client.post(f"{BASE}/series", json={"verstrs": [RUN], "x": x})
        assert r.status_code == 400
