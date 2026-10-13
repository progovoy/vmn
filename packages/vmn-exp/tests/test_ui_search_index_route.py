"""Plan 23 S8 over HTTP: ``GET .../apps/{app}/search?text=&limit=`` answers
the ⌘K "go to run" results — ranked, each with its job — with an early ETag."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

APP = "app"
URL = f"/api/v1/workspaces/ws/apps/{APP}/search"


def _verstr(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _record(root, n, name, parent=None, note=None, archived=False, exit_code=0):
    verstr = _verstr(n)
    folder = os.path.join(root, ".vmn", "store", "runs", APP, verstr)
    os.makedirs(os.path.join(folder, "log"))
    meta = {"format_version": 1, "verstr": verstr, "timestamp": f"2026-01-01T00:00:{n:02d}Z",
            "name": name, "note": note, "archived": archived}
    if parent is not None:
        meta["parent"] = _verstr(parent)
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.write(json.dumps({"timestamp": "t", "type": "metrics", "values": {"loss": 1}}) + "\n")
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        f.write(f"state: finished\nexit_code: {exit_code}\n")


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    for n, name, parent, note in [(1, "lr_grid", None, None), (2, "lr_grid-t1", 1, None),
                                  (3, "lr_grid-t2", 2, "the grid one"), (4, "other", None, None)]:
        _record(root, n, name, parent, note, exit_code=1 if n == 3 else 0)
    _record(root, 5, "grid_archived", archived=True)
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", root)
    return TestClient(create_app(manager))


def test_results_are_ranked_with_their_job(client):
    body = client.get(URL, params={"text": "lr_grid"}).json()
    assert [r["idx"] for r in body["results"]] == [3, 2, 1]
    third = body["results"][0]
    assert third == {"verstr": _verstr(3), "idx": 3, "name": "lr_grid-t2", "status": "failed",
                     "root": _verstr(1), "root_name": "lr_grid", "match": "name"}
    assert body["results"][2]["root"] is None and body["results"][2]["root_name"] is None


def test_at_n_and_verstr_prefix_come_first(client):
    assert client.get(URL, params={"text": "@4"}).json()["results"][0]["match"] == "idx"
    body = client.get(URL, params={"text": "grid"}).json()
    assert [(r["idx"], r["match"]) for r in body["results"]] == [
        (3, "name"), (2, "name"), (1, "name")]
    body = client.get(URL, params={"text": _verstr(2)}).json()
    assert body["results"][0] == dict(body["results"][0], idx=2, match="verstr")


def test_archived_runs_need_archived(client):
    assert client.get(URL, params={"text": "archived"}).json()["results"] == []
    body = client.get(URL, params={"text": "archived", "archived": 1}).json()
    assert [r["idx"] for r in body["results"]] == [5]


def test_limit_is_clamped(client):
    assert len(client.get(URL, params={"text": "0.0.1", "limit": 2}).json()["results"]) == 2
    assert len(client.get(URL, params={"text": "0.0.1", "limit": 500}).json()["results"]) == 4
    assert client.get(URL, params={"text": "0.0.1", "limit": 0}).status_code == 200


def test_a_repeated_search_answers_304(client):
    first = client.get(URL, params={"text": "grid"})
    etag = first.headers["etag"]
    again = client.get(URL, params={"text": "grid"}, headers={"If-None-Match": etag})
    assert again.status_code == 304
    other = client.get(URL, params={"text": "other"}, headers={"If-None-Match": etag})
    assert other.status_code == 200


def test_an_unknown_app_is_404(client):
    assert client.get("/api/v1/workspaces/ws/apps/nope/search", params={"text": "x"}) \
        .status_code == 404
