"""``live_below``/``running_below``/``stuck_below`` select the same outer runs
through every query entry point — ``vmn-exp list --query``, the snapshot
listing ``prune --query`` selects from, the SDK's ``list_runs`` and the UI board's ``top_q`` (the query
the Outer runs page prints as its ``vmn-exp list`` line) — by the Jobs
view rollup's membership rule: settled runs and archived subtrees left out."""
import datetime
import json
import os

import pytest
import yaml
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import seed, verstr

from vmn_exp.core.status import RUN_STATE_FILE

TOP = "depth = 0 and "
QUERIES = {
    "running_below > 0": [1, 2, 9],
    "stuck_below > 0": [12],
    "live_below > 0": [1, 2, 9, 12, 14],
    "live_below = 0 and kind = \"outer\"": [4, 5, 7, 16],
}
TOP_QUERIES = {"running_below > 0": [1, 9], "stuck_below > 0": [12],
               "live_below > 0": [1, 9, 12, 14]}


def _ago(seconds):
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _beating(storage, app, v, age_sec=0):
    storage.save_file(app, v, RUN_STATE_FILE, yaml.safe_dump({
        "state": "running", "pid": 1, "host": "h", "started_at": _ago(age_sec + 60),
        "heartbeat": _ago(age_sec), "heartbeat_interval_sec": 30, "exit_code": None}))


def _stuck(app_layout, storage, app, v):
    _beating(storage, app, v, age_sec=3600)
    path = os.path.join(app_layout.repo_path, ".vmn", "store", "runs", app, v, RUN_STATE_FILE)
    aged = datetime.datetime.now().timestamp() - 3600
    os.utime(path, (aged, aged))


def _seed(app_layout):
    """1 ended -> 2 ended -> 3 running (a grandchild); 4 ended -> 5 ended
    -> 6 never started; 7 ended -> 8 archived -> 10 running; 9 ended -> 11
    running; 12 running -> 13 stuck; 14 running -> 15 waiting; 16 ended ->
    17 stuck (lost)."""
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    for n, parent, code, archived in ((1, None, 0, False), (2, 1, 0, False), (3, 2, None, False),
                                      (4, None, 1, False), (5, 4, 0, False), (6, 5, None, False),
                                      (7, None, 0, False), (8, 7, 0, True), (10, 8, None, False),
                                      (9, None, 0, False), (11, 9, None, False),
                                      (12, None, None, False), (13, 12, None, False),
                                      (14, None, None, False), (15, 14, None, False),
                                      (16, None, 0, False), (17, 16, None, False)):
        seed(storage, app, verstr(n), parent=parent and verstr(parent), archived=archived,
             exit_code=code)
    for n in (3, 10, 11, 12, 14):
        _beating(storage, app, verstr(n))
    for n in (13, 17):
        _stuck(app_layout, storage, app, verstr(n))
    return app, storage


def _expected(numbers):
    return sorted(verstr(n) for n in numbers)


def _cli(app, capfd, query, *extra):
    capfd.readouterr()
    code = _exp(app, action="list", extra_args=["--query", query, "--json", *extra])
    out = capfd.readouterr()
    assert code == 0, out.err
    return sorted(row["verstr"] for row in json.loads(out.out))


def test_cli_list_fills_the_below_counts(app_layout, capfd):
    app, _ = _seed(app_layout)
    for query, numbers in QUERIES.items():
        assert _cli(app, capfd, query) == _expected(numbers), query


def test_the_snapshot_listing_fills_the_below_counts(app_layout):
    from vmn_exp.core.index_list import snapshot_listing

    app, storage = _seed(app_layout)
    for query, numbers in QUERIES.items():
        rows = [r for r in snapshot_listing(storage, app, query)[0] if not r.get("archived")]
        assert sorted(r["verstr"] for r in rows) == _expected(numbers), query


def test_an_archived_job_counts_its_own_subtree(app_layout, capfd):
    app, _ = _seed(app_layout)
    assert _cli(app, capfd, "running_below > 0", "--archived") == _expected([1, 2, 8, 9])


def test_sdk_reader_fills_the_below_counts(app_layout):
    from vmn_exp.sdk.reader import list_runs

    app, storage = _seed(app_layout)
    for query, numbers in QUERIES.items():
        for use_index in (True, False):
            rows = list_runs(app, storage=storage, query=query, use_index=use_index)
            assert sorted(r["verstr"] for r in rows) == _expected(numbers), (query, use_index)
    rows = list_runs(app, storage=storage, query="running_below > 0", status="succeeded")
    assert sorted(r["verstr"] for r in rows) == _expected([1, 2, 9])


def test_the_board_top_q_and_the_cli_keep_the_same_outer_runs(app_layout, capfd):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    app, _ = _seed(app_layout)
    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    client = TestClient(create_app(manager))
    url = f"/api/v1/workspaces/main/apps/{app}/experiments"
    for query, numbers in TOP_QUERIES.items():
        body = client.get(url, params={"top": 1, "top_q": query, "limit": 50})
        assert body.status_code == 200, body.text
        board = sorted(r["verstr"] for r in body.json()["rows"])
        assert board == _expected(numbers), query
        assert _cli(app, capfd, TOP + query) == board, query
