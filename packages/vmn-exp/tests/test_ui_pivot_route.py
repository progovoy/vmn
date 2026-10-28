"""Plan 28 N2 over HTTP: ``GET .../experiments-pivot?rows=&cols=`` (with
``cell=share&match=`` or ``cell=agg&metric=&agg=``, ``scope``, ``q``,
``status``) answers the pivot of the app's runs, a bad field or query is a
400, an unknown scope a 404, and a repeat with its ETag a 304."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

APP = "app"
URL = f"/api/v1/workspaces/ws/apps/{APP}/experiments-pivot"


def _verstr(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _record(root, n, parent=None, tags=None, loss=None):
    folder = os.path.join(root, ".vmn", "store", "runs", APP, _verstr(n))
    os.makedirs(os.path.join(folder, "log"))
    meta = {"format_version": 2, "verstr": _verstr(n), "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = _verstr(parent)
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    entries = [{"timestamp": "t", "type": "create", "params": {}}]
    if tags:
        entries.append({"timestamp": "t", "type": "tags", "set": tags})
    if loss is not None:
        entries.append({"timestamp": "t", "type": "metrics", "values": {"loss": loss}})
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        yaml.dump({"state": "finished", "exit_code": 0, "started_at": "2026-01-01T00:00:00Z",
                   "finished_at": f"2026-01-01T00:{n:02d}:00Z"}, f)


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    _record(root, 1, tags={"kind": "launch"})
    cells = [("d1", "g1", "ok", 1.0), ("d1", "g1", "unstable", 3.0), ("d1", "g2", "ok", 2.0),
             ("d2", "g2", "unstable", 5.0)]
    for n, (date, group, health, loss) in enumerate(cells, 2):
        _record(root, n, parent=1, tags={"date": date, "group": group, "health": health},
                loss=loss)
    _record(root, 9, tags={"date": "d3"})
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", root)
    return TestClient(create_app(manager))


def _get(client, status=200, **params):
    resp = client.get(URL, params={"rows": "tags.date", "cols": "tags.group", **params})
    assert resp.status_code == status, resp.text
    return resp


def test_counts_of_an_outer_runs_subtree(client):
    body = _get(client, scope=_verstr(1)).json()
    assert [h["label"] for h in body["rows"]] == ["d1", "d2"]
    assert [h["label"] for h in body["cols"]] == ["g1", "g2"]
    assert [[c and c["n"] for c in line] for line in body["cells"]] == [[2, 1], [None, 1]]
    assert body["cells"][0][0]["clause"] == 'tags.date = "d1" and tags.group = "g1"'


def test_share_and_aggregate_cells(client):
    share = _get(client, scope=_verstr(1), cell="share", match='tags.health = "unstable"').json()
    assert [[c and c["value"] for c in line] for line in share["cells"]] == [[0.5, 0.0], [None, 1.0]]
    agg = _get(client, scope=_verstr(1), cell="agg", metric="loss", agg="max").json()
    assert [[c and c["value"] for c in line] for line in agg["cells"]] == [[3.0, 2.0], [None, 5.0]]


def test_app_wide_with_a_query(client):
    body = _get(client, q='tags.date in ("d2", "d3")').json()
    assert [h["label"] for h in body["rows"]] == ["d2", "d3"]


@pytest.mark.parametrize("params", [dict(rows="bogus"), dict(cell="share"),
                                    dict(cell="agg"), dict(q="tags.date =="),
                                    dict(cell="share", match="(")])
def test_bad_requests_are_400(client, params):
    _get(client, status=400, **params)


def test_unknown_scope_is_404(client):
    _get(client, status=404, scope=_verstr(77))


def test_a_repeat_with_its_etag_is_304(client):
    first = _get(client, scope=_verstr(1))
    again = client.get(URL, params={"rows": "tags.date", "cols": "tags.group",
                                    "scope": _verstr(1)},
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
