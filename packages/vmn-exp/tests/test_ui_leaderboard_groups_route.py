"""Plan 22 K1 over HTTP: ``GET .../experiments?group=`` answers groups, its
``agg`` defaults to the app's conf ``experiment.ui.group_aggregate``, and bad
fields, aggregates or group keys are the caller's error."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _record(root, n, loss, parent=None):
    verstr = f"0.0.1-dev.abc1234.def5678.r{n}"
    folder = os.path.join(root, ".vmn", "store", "runs", APP, verstr)
    os.makedirs(os.path.join(folder, "log"))
    meta = {"format_version": 1, "verstr": verstr, "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = f"0.0.1-dev.abc1234.def5678.r{parent}"
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.write(json.dumps({"timestamp": "t", "type": "metrics", "values": {"loss": loss}}) + "\n")
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        f.write("state: finished\nexit_code: 0\n")
    return verstr


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
    # sweep 1: losses 1 and 9 (mean 5, min 1); sweep 4: 3 and 4 (mean 3.5, min 3)
    runs = {n: _record(root, n, loss, parent) for n, loss, parent in [
        (1, 0.5, None), (2, 9.0, 1), (3, 1.0, 1), (4, 0.5, None), (5, 3.0, 4), (6, 4.0, 4)]}
    _conf(root, {"metrics": {"loss": {"goal": "min"}}})
    return root, runs


def _client(tmp_path, root):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", root)
    return TestClient(create_app(manager))


def _keys(body):
    return [g["key"] for g in body["groups"]]


def test_group_answers_groups_sorted_by_the_mean(tmp_path, repo):
    root, runs = repo
    body = _client(tmp_path, root).get(BASE, params={"group": "parent", "sort": "loss"}).json()
    assert _keys(body) == [runs[4], runs[1], "(none)"]
    assert body["total_groups"] == 3
    assert body["total_rows"] == 6
    first = body["groups"][0]
    assert first["aggregates"]["loss"] == {"mean": 3.5, "best": 3.0, "median": 3.5,
                                           "min": 3.0, "max": 4.0, "n": 2}
    assert first["target"]["verstr"] == runs[4]


def test_agg_picks_the_sorting_aggregate(tmp_path, repo):
    root, runs = repo
    body = _client(tmp_path, root).get(
        BASE, params={"group": "parent", "sort": "loss", "agg": "best"}).json()
    assert _keys(body) == [runs[1], runs[4], "(none)"]


def test_the_apps_conf_sets_the_default_aggregate(tmp_path, repo):
    root, runs = repo
    _conf(root, {"metrics": {"loss": {"goal": "min"}}, "ui": {"group_aggregate": "min"}})
    client = _client(tmp_path, root)
    body = client.get(BASE, params={"group": "parent", "sort": "loss"}).json()
    assert _keys(body) == [runs[1], runs[4], "(none)"]
    explicit = client.get(BASE, params={"group": "parent", "sort": "loss", "agg": "mean"}).json()
    assert _keys(explicit) == [runs[4], runs[1], "(none)"]


def test_an_invalid_conf_aggregate_falls_back_to_the_mean(tmp_path, repo):
    root, runs = repo
    _conf(root, {"metrics": {"loss": {"goal": "min"}}, "ui": {"group_aggregate": "sum"}})
    body = _client(tmp_path, root).get(BASE, params={"group": "parent", "sort": "loss"}).json()
    assert _keys(body) == [runs[4], runs[1], "(none)"]


def test_rows_per_group_caps_and_group_key_pages(tmp_path, repo):
    root, runs = repo
    client = _client(tmp_path, root)
    body = client.get(BASE, params={"group": "parent", "rows_per_group": 1, "limit": 1}).json()
    assert len(body["groups"]) == 1
    assert len(body["groups"][0]["rows"]) == 1
    assert body["groups"][0]["rows_total"] == 2
    page = client.get(BASE, params={"group": "parent", "group_key": runs[1],
                                    "offset": 1, "limit": 5}).json()
    assert [r["verstr"] for r in page["rows"]] == [runs[3]]
    assert page["rows_total"] == 2


def test_rows_per_group_is_capped_at_a_hundred(tmp_path, repo):
    root, _ = repo
    client = _client(tmp_path, root)
    assert client.get(BASE, params={"group": "parent", "rows_per_group": 101}).status_code == 400
    assert client.get(BASE, params={"group": "parent", "rows_per_group": 0}).status_code == 400


@pytest.mark.parametrize("params", [
    {"group": "inputs"}, {"group": "parent", "agg": "sum"}, {"group": "parent", "last": 3},
])
def test_bad_grouping_parameters_are_400(tmp_path, repo, params):
    root, _ = repo
    assert _client(tmp_path, root).get(BASE, params=params).status_code == 400


def test_an_unknown_group_key_is_404(tmp_path, repo):
    root, _ = repo
    response = _client(tmp_path, root).get(BASE, params={"group": "parent", "group_key": "x"})
    assert response.status_code == 404


def test_grouped_answers_have_their_own_etag(tmp_path, repo):
    root, _ = repo
    client = _client(tmp_path, root)
    flat = client.get(BASE, params={"limit": 50})
    grouped = client.get(BASE, params={"limit": 50, "group": "parent"})
    by_min = client.get(BASE, params={"limit": 50, "group": "parent", "agg": "min"})
    tags = {flat.headers["etag"], grouped.headers["etag"], by_min.headers["etag"]}
    assert len(tags) == 3
    again = client.get(BASE, params={"limit": 50, "group": "parent"},
                       headers={"If-None-Match": grouped.headers["etag"]})
    assert again.status_code == 304


def test_without_group_the_list_is_unchanged(tmp_path, repo):
    root, _ = repo
    body = _client(tmp_path, root).get(BASE, params={"limit": 50}).json()
    assert set(body) == {"rows", "total"}
    assert body["total"] == 6
