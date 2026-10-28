"""Plan 28 N1 end to end: ``up.*`` fields select the same runs through every
query entry point — ``vmn-exp list --query``, ``prune --query`` (dry run), the
SDK's ``list_runs`` and the UI board's ``?q=`` — even when a status clause or
the archived filter leaves the ancestors out of the rows kept."""
import json
import os

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import seed, verstr

QUERIES = {
    'up.params.trade_date = "d1"': [2, 3, 4],
    'up.params.trade_date = "d1" and status = "failed"': [3],
    'up.params.group = "fx" and status = "failed"': [3, 7],
    'up(name = "study-b").params.group = "fx"': [7],
    'up.params.trade_date = "d2" and status in ("failed")': [6, 7],
}


def _seed(app_layout):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    seed(storage, app, verstr(1), params={"trade_date": "d1"}, archived=True, exit_code=0)
    seed(storage, app, verstr(2), parent=verstr(1), params={"group": "fx"}, exit_code=0)
    seed(storage, app, verstr(3), parent=verstr(2), exit_code=1)
    seed(storage, app, verstr(4), parent=verstr(2), exit_code=0)
    seed(storage, app, verstr(5), params={"trade_date": "d2"}, exit_code=0)
    seed(storage, app, verstr(6), parent=verstr(5), params={"group": "fx"}, name="study-b",
         exit_code=1)
    seed(storage, app, verstr(7), parent=verstr(6), exit_code=1)
    return app, storage


def _expected(numbers):
    return sorted(verstr(n) for n in numbers)


def _cli_list(app, capfd, query):
    capfd.readouterr()
    code = _exp(app, action="list", extra_args=["--query", query, "--json"])
    out = capfd.readouterr()
    assert code == 0, out.err
    return sorted(row["verstr"] for row in json.loads(out.out))


def _cli_prune(app, capfd, query):
    capfd.readouterr()
    code = _exp(app, action="prune", extra_args=["--query", query, "--dry-run"])
    out = capfd.readouterr().out
    assert code == 0, out
    return sorted(line.strip() for line in out.splitlines() if line.startswith("  0."))


def test_cli_list_and_prune_select_the_same_runs(app_layout, capfd):
    app, _ = _seed(app_layout)
    for query, numbers in QUERIES.items():
        assert _cli_list(app, capfd, query) == _expected(numbers), query
        assert _cli_prune(app, capfd, query) == _expected(numbers), query


def test_sdk_reader_selects_the_same_runs(app_layout):
    from vmn_exp.sdk.reader import list_runs

    app, storage = _seed(app_layout)
    for query, numbers in QUERIES.items():
        for use_index in (True, False):
            rows = list_runs(app, storage=storage, query=query, use_index=use_index)
            assert sorted(r["verstr"] for r in rows) == _expected(numbers), (query, use_index)
    rows = list_runs(app, storage=storage, query='up.params.group = "fx"', status="failed")
    assert sorted(r["verstr"] for r in rows) == _expected([3, 7])


def test_ui_board_selects_the_same_runs(app_layout):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app, _ = _seed(app_layout)
    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    client = TestClient(create_app(manager))
    url = f"/api/v1/workspaces/main/apps/{app}/experiments"
    for query, numbers in QUERIES.items():
        response = client.get(url, params={"q": query})
        assert response.status_code == 200, response.text
        assert sorted(r["verstr"] for r in response.json()) == _expected(numbers), query
    response = client.get(url, params={"q": 'up.params.group = "fx"', "status": "failed"})
    assert sorted(r["verstr"] for r in response.json()) == _expected([3, 7])
    assert client.get(url, params={"q": "up.status = 1"}).status_code == 400


def test_ui_board_groups_by_an_ancestor_field(app_layout):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app, _ = _seed(app_layout)
    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    client = TestClient(create_app(manager))
    url = f"/api/v1/workspaces/main/apps/{app}/experiments"
    response = client.get(url, params={"group": "up.params.trade_date", "status": "failed"})
    assert response.status_code == 200, response.text
    groups = {g["key"]: sorted(r["verstr"] for r in g["rows"]) for g in response.json()["groups"]}
    assert groups == {"d1": _expected([3]), "d2": _expected([6, 7])}
    assert client.get(url, params={"group": "up.status"}).status_code == 400
