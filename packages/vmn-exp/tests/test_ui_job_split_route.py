"""Plan 28 P3 over HTTP: ``.../experiments/{v}/summary?split=tags.kind``
adds ``split`` and ``by`` (counts and durations per value), the default
comes from the app's conf ``experiment.ui.split_by``, and a field that is
not a tag or a param is the caller's error."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _verstr(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _record(root, n, kind=None, parent=None, exit_code=0, lr=None):
    folder = os.path.join(root, ".vmn", "store", "runs", APP, _verstr(n))
    os.makedirs(os.path.join(folder, "log"))
    meta = {"format_version": 2, "verstr": _verstr(n), "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = _verstr(parent)
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    entries = [{"timestamp": "t", "type": "create", "params": {"lr": lr} if lr else {}}]
    if kind:
        entries.append({"timestamp": "t", "type": "tags", "set": {"kind": kind}})
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        yaml.dump({"state": "finished", "exit_code": exit_code,
                   "started_at": "2026-01-01T00:00:00Z",
                   "finished_at": f"2026-01-01T00:{n:02d}:00Z"}, f)


def _conf(root, experiment):
    folder = os.path.join(root, ".vmn", APP)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "conf.yml"), "w") as f:
        yaml.dump({"conf": {"experiment": experiment}}, f)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    _record(root, 1, kind="launch")
    for n in range(2, 8):
        _record(root, n, kind="trial", parent=1, lr=0.1)
    _record(root, 8, kind="refit", parent=1, exit_code=1, lr=0.2)
    _record(root, 9, kind="refit", parent=1, lr=0.2)
    _record(root, 10, parent=1)
    return root


def _client(tmp_path, root):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", root)
    return TestClient(create_app(manager))


def _summary(client, **params):
    resp = client.get(f"{BASE}/{_verstr(1)}/summary", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_split_adds_counts_and_durations_per_value(tmp_path, repo):
    body = _summary(_client(tmp_path, repo), split="tags.kind")
    assert body["split"] == "tags.kind"
    assert [(e["key"], e["label"], e["total"]) for e in body["by"]] == [
        ("trial", "trial", 6), ("refit", "refit", 2), ("∅", "(none)", 1)]
    trial, refit, untagged = body["by"]
    assert trial["counts"]["succeeded"] == 6 and trial["done"] == 6
    assert trial["clause"] == 'tags.kind = "trial"'
    assert refit["counts"]["failed"] == 1 and refit["failed_pct"] == 50.0
    assert refit["duration"]["n"] == 2
    assert refit["duration"]["p90"] == pytest.approx(540, rel=0.011)
    assert untagged["clause"] == "tags.kind = null"
    # The whole job's tiles are unchanged beside the split.
    assert body["total"] == 9 and body["counts"]["failed"] == 1


def test_a_param_splits_too(tmp_path, repo):
    body = _summary(_client(tmp_path, repo), split="params.lr")
    assert [(e["key"], e["total"], e["clause"]) for e in body["by"]] == [
        ("0.1", 6, "params.lr = 0.1"), ("0.2", 2, "params.lr = 0.2"),
        ("∅", 1, "params.lr = null")]


def test_without_split_the_summary_has_none(tmp_path, repo):
    body = _summary(_client(tmp_path, repo))
    assert body["split"] is None and body["by"] is None


def test_the_apps_conf_sets_the_default_split(tmp_path, repo):
    _conf(repo, {"ui": {"split_by": "tags.kind"}})
    client = _client(tmp_path, repo)
    body = _summary(client)
    assert body["split"] == "tags.kind" and body["by"][0]["key"] == "trial"
    assert _summary(client, split="params.lr")["split"] == "params.lr"


def test_an_invalid_conf_split_is_ignored(tmp_path, repo):
    _conf(repo, {"ui": {"split_by": "metrics.loss"}})
    assert _summary(_client(tmp_path, repo))["split"] is None


@pytest.mark.parametrize("field", ["kind", "metrics.loss", "tags."])
def test_a_split_on_another_field_is_a_400(tmp_path, repo, field):
    resp = _client(tmp_path, repo).get(f"{BASE}/{_verstr(1)}/summary", params={"split": field})
    assert resp.status_code == 400


def test_the_etag_follows_the_split(tmp_path, repo):
    client = _client(tmp_path, repo)
    plain = client.get(f"{BASE}/{_verstr(1)}/summary")
    split = client.get(f"{BASE}/{_verstr(1)}/summary", params={"split": "tags.kind"},
                       headers={"If-None-Match": plain.headers["etag"]})
    assert split.status_code == 200 and split.json()["by"]
