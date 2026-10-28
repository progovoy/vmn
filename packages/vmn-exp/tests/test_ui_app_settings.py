"""Plan 28 A0 over HTTP: a store workspace sorts, summarizes and groups by
the app's store settings; a git workspace's conf beats them; they beat a
run's own declarations; editors read and write them through the API."""
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vmn_exp.core.app_settings_store import read_settings_text, write_settings  # noqa: E402
from vmn_exp.storage.areas import RUNS  # noqa: E402
from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: E402
from vmn_exp.storage.open import open_storage  # noqa: E402

from report_api_helpers import HeaderAuth, user  # noqa: E402

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"


def _run(storage, n, entries, parent=None):
    verstr = f"0.0.1-dev.abc1234.def5678.r{n}"
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = f"0.0.1-dev.abc1234.def5678.r{parent}"
    storage.save(APP, verstr, meta, {})
    for entry in entries:
        storage.append_log_entry(APP, verstr, "w", dict(entry, timestamp="t"))
    storage.save_file(APP, verstr, "run_state.yml", "state: finished\nexit_code: 0\n")
    return verstr


def _loss(value):
    return {"type": "metrics", "values": {"loss": value}}


def _runs(storage):
    """Sweep r1 (losses 9, 1: mean 5, min 1) and sweep r4 (3, 4: mean 3.5, min 3)."""
    return {n: _run(storage, n, [_loss(loss)], parent) for n, loss, parent in [
        (1, 0.5, None), (2, 9.0, 1), (3, 1.0, 1), (4, 0.5, None), (5, 3.0, 4), (6, 4.0, 4)]}


def _create(manager, auth=None, read_only=False):
    from vmn_exp.ui.server import create_app

    return TestClient(create_app(manager, auth=auth, read_only=read_only))


@pytest.fixture
def store(tmp_path):
    """``(client factory, runs storage)`` of a ``file://`` store workspace."""
    from vmn_exp.ui.workspaces import WorkspaceManager

    uri = f"file://{tmp_path}/store"
    storage = open_storage(uri, area=RUNS)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", uri)
    return (lambda **kw: _create(manager, **kw)), storage


@pytest.fixture
def repo(tmp_path):
    """``(client, checkout root, its store)`` of a git workspace."""
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    storage = LocalSnapshotStorage(str(root / ".vmn" / "store"), "runs")
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return _create(manager), str(root), storage


def _conf(root, experiment):
    folder = os.path.join(root, ".vmn", APP)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "conf.yml"), "w") as f:
        yaml.dump({"conf": {"experiment": experiment}}, f)


def _grouped(client):
    return client.get(f"{BASE}/experiments", params={"group": "parent", "sort": "loss"}).json()


def test_a_store_workspace_takes_the_schema_from_its_settings(store):
    client_of, storage = store
    runs = _runs(storage)
    write_settings(storage, APP, "metrics: {loss: {goal: max, primary: true}}\n")
    client = client_of()
    assert client.get(f"{BASE}/metrics-schema").json() == {
        "loss": {"goal": "max", "primary": True}}
    rows = client.get(f"{BASE}/experiments").json()
    assert [r["verstr"] for r in rows][:2] == [runs[2], runs[6]]


def test_a_store_setting_beats_a_run_declaration(store):
    client_of, storage = store
    low = _run(storage, 1, [_loss(0.1)])
    high = _run(storage, 2, [{"type": "define_metric", "name": "loss", "goal": "max"},
                             _loss(0.9)])
    write_settings(storage, APP, "metrics: {loss: {goal: min}}\n")
    client = client_of()
    assert client.get(f"{BASE}/metrics-schema").json() == {"loss": {"goal": "min"}}
    rows = client.get(f"{BASE}/experiments", params={"sort": "loss"}).json()
    assert [r["verstr"] for r in rows] == [low, high]


def test_a_store_workspace_takes_the_group_aggregate_from_its_settings(store):
    client_of, storage = store
    runs = _runs(storage)
    write_settings(storage, APP, "metrics: {loss: {goal: min}}\nui: {group_aggregate: min}\n")
    body = _grouped(client_of())
    assert body["aggregate"] == "min"
    assert [g["key"] for g in body["groups"]] == [runs[1], runs[4]]


def test_a_settings_summary_policy_summarizes_store_rows(store):
    client_of, storage = store
    verstr = _run(storage, 1, [_loss(5.0), _loss(1.0), _loss(3.0)])
    write_settings(storage, APP, "metrics: {loss: {summary: min}}\n")
    (row,) = client_of().get(f"{BASE}/experiments").json()
    assert row["verstr"] == verstr and row["metrics"]["loss"] == 1.0


def test_a_git_workspace_reads_settings_below_its_conf(repo):
    client, root, storage = repo
    runs = _runs(storage)
    write_settings(storage, APP, "metrics: {loss: {goal: max}, acc: {goal: max}}\n"
                                 "ui: {group_aggregate: min}\n")
    _conf(root, {"metrics": {"loss": {"goal": "min"}}})
    assert client.get(f"{BASE}/metrics-schema").json() == {
        "loss": {"goal": "min"}, "acc": {"goal": "max"}}
    body = _grouped(client)
    assert body["aggregate"] == "min" and [g["key"] for g in body["groups"]][:2] == [
        runs[1], runs[4]]
    _conf(root, {"metrics": {"loss": {"goal": "min"}}, "ui": {"group_aggregate": "mean"}})
    assert _grouped(client)["aggregate"] == "mean"


def test_the_settings_route_reads_and_writes_the_file(store):
    client_of, storage = store
    client = client_of()
    assert client.get(f"{BASE}/settings").json()["text"] == ""
    text = "# ours\nui: {group_aggregate: best}\n"
    r = client.put(f"{BASE}/settings", json={"text": text})
    assert r.status_code == 200, r.text
    assert r.json()["settings"] == {"ui": {"group_aggregate": "best"}}
    assert read_settings_text(storage, APP) == text
    body = client.get(f"{BASE}/settings").json()
    assert body["text"] == text and body["settings"] == {"ui": {"group_aggregate": "best"}}
    assert body["updated_at"]
    assert _grouped(client)["aggregate"] == "best"


def test_invalid_settings_are_a_400_and_change_nothing(store):
    client_of, storage = store
    client = client_of()
    client.put(f"{BASE}/settings", json={"text": "ui: {group_aggregate: max}\n"})
    r = client.put(f"{BASE}/settings", json={"text": "ui: {group_aggregate: sum}\n"})
    assert r.status_code == 400 and "group_aggregate" in r.json()["detail"]
    assert client.put(f"{BASE}/settings", json={"text": 3}).status_code == 400
    assert read_settings_text(storage, APP) == "ui: {group_aggregate: max}\n"


def test_writing_settings_needs_an_editor(store):
    from vmn_exp.ui.auth import AuthenticatorChain

    client = store[0](auth=AuthenticatorChain([HeaderAuth()]))
    text = {"text": "ui: {stale_after_min: 9}\n"}
    assert client.get(f"{BASE}/settings", headers=user("v", "viewer")).status_code == 200
    assert client.put(f"{BASE}/settings", json=text,
                      headers=user("v", "viewer")).status_code == 403
    r = client.put(f"{BASE}/settings", json=text, headers=user("e", "editor"))
    assert r.status_code == 200
    body = client.get(f"{BASE}/settings", headers=user("v", "viewer")).json()
    assert body["updated_by"]["name"] == "E"


def test_a_read_only_server_refuses_settings_writes(store):
    client = store[0](read_only=True)
    r = client.put(f"{BASE}/settings", json={"text": "ui: {stale_after_min: 9}\n"})
    assert r.status_code == 403


def test_a_store_workspace_takes_the_default_split_from_its_settings(store):
    client_of, storage = store
    outer = _run(storage, 1, [])
    for n, kind in [(2, "trial"), (3, "trial"), (4, "refit")]:
        _run(storage, n, [{"type": "tags", "set": {"kind": kind}}], parent=1)
    write_settings(storage, APP, "ui: {split_by: tags.kind}\n")
    body = client_of().get(f"{BASE}/experiments/{outer}/summary").json()
    assert body["split"] == "tags.kind"
    assert [(e["key"], e["total"]) for e in body["by"]] == [("trial", 2), ("refit", 1)]


def test_an_attention_query_that_does_not_compile_is_a_400(store):
    client = store[0]()
    r = client.put(f"{BASE}/settings", json={"text": "ui: {attention: [{key: w, query: 'statuz = 1'}]}\n"})
    assert r.status_code == 400 and "ui.attention[0].query" in r.json()["detail"]
    assert client.get(f"{BASE}/settings").json()["text"] == ""
