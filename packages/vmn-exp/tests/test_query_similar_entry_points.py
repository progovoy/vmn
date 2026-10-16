"""Plan 24 F5 end to end: ``intent``, ``keywords`` and ``similar("…")`` select
the same runs through every query entry point — ``vmn-exp list --query``,
``prune --query`` (dry run), the SDK's ``list_runs``/``runs_dataframe`` and
the UI board's ``?q=``."""
import json
import os

import pytest
from exp_helpers import _bootstrap, _exp, _storage
from similar_seed import seed, verstr

QUERIES = {
    'intent ~ "focal"': [1, 2],
    'keywords ~ "imbalance"': [1],
    'similar("focal loss") and status = "succeeded"': [1, 4],
    'similar("focal loss")': [1, 2, 4],
    'not similar("focal") and has_intent = false': [5],
}


def _seed(app_layout):
    _bootstrap(app_layout)
    app, storage = app_layout.app_name, _storage(app_layout)
    seed(storage, app, verstr(1), exit_code=0,
         intent={"text": "Focal loss for the tail", "keywords": ["class imbalance"]})
    seed(storage, app, verstr(2), intent={"text": "focal losses again"}, exit_code=1)
    seed(storage, app, verstr(3), intent={"text": "label smoothing"}, exit_code=0)
    seed(storage, app, verstr(4), note="the focal loss baseline", exit_code=0)
    seed(storage, app, verstr(5), note="plain", exit_code=0)
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


def test_cli_list_reports_a_bad_similar_call(app_layout, capfd):
    app, _ = _seed(app_layout)
    capfd.readouterr()
    assert _exp(app, action="list", extra_args=["--query", "similar(1)"]) == 1
    assert "similar() takes one quoted text" in capfd.readouterr().err


def test_sdk_reader_selects_the_same_runs(app_layout):
    from vmn_exp.sdk.reader import list_runs

    app, storage = _seed(app_layout)
    for query, numbers in QUERIES.items():
        for use_index in (True, False):
            rows = list_runs(app, storage=storage, query=query, use_index=use_index)
            assert sorted(r["verstr"] for r in rows) == _expected(numbers), (query, use_index)


def test_sdk_dataframe_selects_the_same_runs(app_layout):
    pytest.importorskip("pandas")
    from vmn_exp.sdk.reader import runs_dataframe

    app, storage = _seed(app_layout)
    frame = runs_dataframe(app, storage=storage, query='similar("focal loss")')
    assert sorted(frame["run_id"]) == _expected(QUERIES['similar("focal loss")'])


def test_similar_query_filter_reads_the_intent_fields(app_layout, capfd):
    app, _ = _seed(app_layout)
    for query, numbers in (('keywords ~ "imbalance"', [1]),
                           ('similar("tail") or intent ~ "again"', [1, 2])):
        capfd.readouterr()
        code = _exp(app, action="similar", extra_args=[
            "--context", "focal loss", "--text-only", "--query", query, "--json"])
        out = capfd.readouterr()
        assert code == 0, out.err
        assert sorted(i["verstr"] for i in json.loads(out.out)) == _expected(numbers), query


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
    assert client.get(url, params={"q": 'similar("")'}).status_code == 400
