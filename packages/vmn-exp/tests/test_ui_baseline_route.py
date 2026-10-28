"""Plan 28 N3 over HTTP: ``GET .../experiments/{v}/baseline`` compares an
outer run with its baseline by the conf's ``experiment.ui.baseline`` rule
(``match=``/``by=``/``to=`` override it), ``GET .../experiments-baselines?v=``
answers the chips of many outer runs at once; a bad field or ``to`` itself
is a 400, no outer run a 404, and a repeat with its ETag a 304."""
import json
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

APP = "app"
BASE = f"/api/v1/workspaces/ws/apps/{APP}"
RULE = {"match": ["params.table_name"], "children_by": "params.trade_date"}


def _verstr(n):
    return f"0.0.1-dev.abc1234.def5678.r{n}"


def _record(root, n, parent=None, params=None, value=None):
    folder = os.path.join(root, ".vmn", "store", "runs", APP, _verstr(n))
    os.makedirs(os.path.join(folder, "log"))
    meta = {"format_version": 2, "verstr": _verstr(n), "timestamp": f"2026-01-01T00:00:{n:02d}Z"}
    if parent is not None:
        meta["parent"] = _verstr(parent)
    with open(os.path.join(folder, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    entries = [{"timestamp": "t", "type": "create", "params": params or {}}]
    if value is not None:
        entries.append({"timestamp": "t", "type": "metrics", "values": {"best_value": value}})
    with open(os.path.join(folder, "log", "w.jsonl"), "w") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)
    with open(os.path.join(folder, "run_state.yml"), "w") as f:
        yaml.dump({"state": "finished", "exit_code": 0, "started_at": "2026-01-01T00:00:00Z",
                   "finished_at": f"2026-01-01T00:{n:02d}:00Z"}, f)


def _launch(root, n, values):
    _record(root, n, params={"table_name": "t1"})
    for i, value in enumerate(values, 1):
        _record(root, n + i, parent=n, params={"trade_date": f"2024-0{i}"}, value=value)


@pytest.fixture
def client(tmp_path):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    _launch(str(root), 1, [1.0, 1.0, 1.0])
    _launch(str(root), 5, [1.1, 0.2, 1.0])
    _record(str(root), 9)
    os.makedirs(root / ".vmn" / APP)
    conf = {"experiment": {"metrics": {"best_value": {"goal": "max"}}, "ui": {"baseline": RULE}}}
    with open(root / ".vmn" / APP / "conf.yml", "w") as f:
        yaml.dump({"conf": conf}, f)
    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.attach_path("ws", str(root))
    return TestClient(create_app(manager))


def _get(client, verstr, status=200, **params):
    resp = client.get(f"{BASE}/experiments/{verstr}/baseline", params=params)
    assert resp.status_code == status, resp.text
    return resp


def test_the_conf_rule_picks_the_baseline_and_pairs_the_dates(client):
    body = _get(client, _verstr(5)).json()
    assert body["baseline"]["verstr"] == _verstr(1)
    assert [p["label"] for p in body["pairs"]] == ["2024-01", "2024-02", "2024-03"]
    assert body["chip"]["state"] == "worse"
    assert body["chip"]["text"].startswith("▼ best_value from 2024-02 (1 of 3")


def test_url_parameters_override_the_rule(client):
    assert _get(client, _verstr(5), by="").json()["pairs"] == []
    body = _get(client, _verstr(5), match="params.table_name", to=_verstr(1)).json()
    assert body["baseline"]["source"] == "to"


@pytest.mark.parametrize("params", [dict(match="status"), dict(by="branch"),
                                    dict(to=_verstr(5))])
def test_bad_requests_are_400(client, params):
    _get(client, _verstr(5), status=400, **params)


@pytest.mark.parametrize("verstr, params", [(_verstr(9), {}), (_verstr(77), {}),
                                            (_verstr(5), {"to": _verstr(9)})])
def test_no_outer_run_is_404(client, verstr, params):
    _get(client, verstr, status=404, **params)


def test_a_repeat_with_its_etag_is_304(client):
    first = _get(client, _verstr(5))
    again = client.get(f"{BASE}/experiments/{_verstr(5)}/baseline",
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


def test_many_chips_in_one_request(client):
    resp = client.get(f"{BASE}/experiments-baselines",
                      params=[("v", _verstr(5)), ("v", _verstr(1)), ("v", _verstr(9))])
    assert resp.status_code == 200, resp.text
    chips = resp.json()["chips"]
    assert chips[_verstr(5)]["state"] == "worse"
    assert chips[_verstr(5)]["baseline"]["verstr"] == _verstr(1)
    assert chips[_verstr(1)] is None and chips[_verstr(9)] is None
    again = client.get(f"{BASE}/experiments-baselines", params=[("v", _verstr(5))],
                       headers={"If-None-Match": resp.headers["etag"]})
    assert again.status_code == 200  # another set of runs, another answer


def test_too_many_chips_are_400(client):
    resp = client.get(f"{BASE}/experiments-baselines", params=[("v", _verstr(5))] * 201)
    assert resp.status_code == 400
