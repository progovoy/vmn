"""``.../experiments-columns``: whole-set chart data over the filtered, sorted
rows, one aligned array per requested key; plus ``archived`` hiding on the
list/facets routes and the cached metrics schema."""
import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_index_snapshot import IndexSnapshot
from version_stamp.core.experiment_log import experiment_row
from version_stamp.ui import leaderboard_cache as lb
from version_stamp.ui import schema_cache
from version_stamp.ui.readers import experiments as exp_reader

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _ts(i):
    return f"2026-01-01T00:00:{i:02d}Z"


def _app(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    storage = get_snapshot_storage("local", vmn_root_path=str(root), subdir="experiments")

    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager)), storage, root


@pytest.fixture
def served(tmp_path):
    return _app(tmp_path)


def _run(storage, i, loss=None, **params):
    verstr = f"1.0.0-dev.r{i:04d}"
    meta = {"verstr": verstr, "timestamp": _ts(i), "note": f"n{i}"}
    storage.save(APP, verstr, meta, {})
    storage.append_log_entry(APP, verstr, "w", {"timestamp": _ts(i), "type": "create", "params": params})
    if loss is not None:
        storage.append_log_entry(
            APP, verstr, "w", {"timestamp": _ts(i), "type": "metrics", "values": {"loss": loss}}
        )
    return verstr


def test_columns_are_aligned_over_the_whole_sorted_set(served):
    client, storage, _ = served
    for i, loss in enumerate([0.3, None, 0.1, 0.2]):
        _run(storage, i, loss=loss, opt="adam" if i % 2 else "sgd")

    r = client.get(f"{BASE}/experiments-columns?keys=metrics.loss,params.opt,timestamp,status,name"
                   "&sort=loss&order=asc")

    assert r.status_code == 200
    body = r.json()
    assert body["verstrs"] == [f"1.0.0-dev.r{i:04d}" for i in (2, 3, 0, 1)]
    assert body["idx"] == [3, 4, 1, 2]
    assert body["total"] == 4
    assert body["columns"] == {
        "metrics.loss": [0.1, 0.2, 0.3, None],
        "params.opt": ["sgd", "adam", "sgd", "adam"],
        "timestamp": [_ts(2), _ts(3), _ts(0), _ts(1)],
        "status": ["created"] * 4,
        "name": ["n2", "n3", "n0", "n1"],
    }


def test_columns_filter_limit_and_304(served):
    client, storage, _ = served
    for i in range(6):
        _run(storage, i, loss=i / 10)

    url = f"{BASE}/experiments-columns?keys=metrics.loss&q=metrics.loss%20%3E%3D%200.2&limit=2"
    first = client.get(url)
    body = first.json()
    assert body["total"] == 4
    assert len(body["verstrs"]) == 2 and len(body["columns"]["metrics.loss"]) == 2

    again = client.get(url, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    other = client.get(url + "&sort=loss", headers={"If-None-Match": first.headers["etag"]})
    assert other.status_code == 200


def test_columns_reject_unknown_keys_and_bad_queries(served):
    client, storage, _ = served
    _run(storage, 0, loss=0.1)
    assert client.get(f"{BASE}/experiments-columns?keys=nope").status_code == 400
    assert client.get(f"{BASE}/experiments-columns?keys=metrics.loss&q=statuz%20%3D%201").status_code == 400


def test_the_columns_limit_is_clamped():
    rows = [experiment_row(i + 1, {"verstr": f"v{i}"}, []) for i in range(30)]
    snap = IndexSnapshot.build(APP, 1, rows, {})
    cache = lb.LeaderboardCache()
    assert len(cache.columns(snap, {}, keys=["name"], limit=10)["verstrs"]) == 10
    assert lb.clamp_columns_limit(None) == 20000
    assert lb.clamp_columns_limit(10 ** 9) == 50000
    assert lb.clamp_columns_limit(-3) == 0


def test_columns_are_memoized_per_snapshot(monkeypatch):
    rows = [experiment_row(i + 1, {"verstr": f"v{i}"}, []) for i in range(30)]
    snap = IndexSnapshot.build(APP, 1, rows, {})
    cache = lb.LeaderboardCache()
    first = cache.columns(snap, {}, keys=["name"])
    assert cache.columns(snap, {}, keys=["name"]) is first


def _synthetic_client(rows):
    """The leaderboard routes alone, over a snapshot of *rows* (the index
    does not fold ``archived`` yet: the rows carry it directly)."""
    from fastapi import FastAPI

    from version_stamp.ui import routes_leaderboard

    snap = IndexSnapshot.build(APP, 1, rows, {})
    app = FastAPI()
    routes_leaderboard.register(app, "/api/v1", lambda ws, tag: (snap, {}), lb.LeaderboardCache())
    return TestClient(app)


def test_archived_rows_are_hidden_from_list_columns_and_facets():
    rows = [experiment_row(i + 1, {"verstr": f"1.0.0-dev.r{i:04d}"}, []) for i in range(2)]
    rows[1]["archived"] = True
    client = _synthetic_client(rows)

    listed = client.get(f"{BASE}/experiments?limit=10").json()
    assert [r["verstr"] for r in listed["rows"]] == ["1.0.0-dev.r0000"]
    everything = client.get(f"{BASE}/experiments?limit=10&archived=1")
    assert everything.json()["total"] == 2
    assert client.get(f"{BASE}/experiments-columns?keys=name").json()["total"] == 1
    assert client.get(f"{BASE}/experiments-columns?keys=name&archived=1").json()["total"] == 2
    assert client.get(f"{BASE}/experiments-facets").json()["total"] == 1
    assert client.get(f"{BASE}/experiments-facets?archived=1").json()["total"] == 2

    hidden_tag = client.get(f"{BASE}/experiments?limit=10").headers["etag"]
    shown = client.get(f"{BASE}/experiments?limit=10&archived=1",
                       headers={"If-None-Match": hidden_tag})
    assert shown.status_code == 200


def _write_conf(root, text):
    path = os.path.join(str(root), ".vmn", APP, "conf.yml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def _counting_schema_reads(monkeypatch):
    calls = []
    real = exp_reader.metrics_schema

    def counted(root_path, app_name):
        calls.append(app_name)
        return real(root_path, app_name)

    monkeypatch.setattr(exp_reader, "metrics_schema", counted)
    return calls


def test_the_metrics_schema_is_reread_only_when_the_conf_changes(tmp_path, monkeypatch):
    calls = _counting_schema_reads(monkeypatch)
    cache = schema_cache.MetricsSchemaCache()
    root = str(tmp_path)
    assert cache.get(root, APP) == {}
    path = _write_conf(root, "conf:\n  experiment:\n    metrics:\n      loss: {goal: min}\n")

    assert cache.get(root, APP) == {"loss": {"goal": "min"}}
    assert cache.get(root, APP) == {"loss": {"goal": "min"}}
    assert len(calls) == 2

    _write_conf(root, "conf:\n  experiment:\n    metrics:\n      acc: {goal: max}\n")
    assert cache.get(root, APP) == {"acc": {"goal": "max"}}
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
    cache.get(root, APP)
    assert len(calls) == 4


def test_list_polls_do_not_reread_the_conf(served, monkeypatch):
    client, storage, root = served
    _write_conf(root, "conf:\n  experiment:\n    metrics:\n      loss: {goal: max}\n")
    for i in range(3):
        _run(storage, i, loss=i / 10)
    calls = _counting_schema_reads(monkeypatch)

    for _ in range(3):
        rows = client.get(f"{BASE}/experiments?limit=10&sort=loss").json()["rows"]
    assert [r["metrics"]["loss"] for r in rows] == [0.2, 0.1, 0.0]
    assert len(calls) == 1
