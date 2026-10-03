"""``GET /api/v1/search``: one query over every workspace the caller can see
(plan 11 §4.4), answered in Python, or in SQL with a Postgres ``search_dsn``."""
import os

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from pg_fixture import pg_dsn, pg_server_dsn  # noqa: F401
from vmn_exp.ui.auth import AuthenticatorChain
from vmn_exp.ui.auth.principal import VIEWER, Principal

SEARCH = "/api/v1/search"


def _run(root, app, verstr, loss, note="n"):
    path = os.path.join(root, ".vmn", "store", "runs", app, verstr)
    os.makedirs(os.path.join(path, "log"), exist_ok=True)
    meta = {
        "verstr": verstr, "code_verstr": verstr, "timestamp": "2026-09-21T12:00:00",
        "note": note, "branch": "master", "base_version": "0.0.1",
    }
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump(meta, f)
    with open(os.path.join(path, "log", "w0.jsonl"), "w") as f:
        f.write(
            '{"timestamp": "2026-09-21T12:00:01Z", "type": "metrics",'
            f' "values": {{"loss": {loss}}}}}\n'
        )


class _Fixed:
    PRINCIPALS = {
        "Bearer one": Principal("one", "one", {"ws1": VIEWER}),
        "Bearer all": Principal("all", "all", {"*": VIEWER}),
        "Bearer none": Principal("none", "none", {}),
    }

    def authenticate(self, request):
        return self.PRINCIPALS.get(request.headers.get("Authorization", ""))


def _client(tmp_path, auth=False, **kw):
    from vmn_exp.ui.server import create_app
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "ui_data"))
    for ws, app, runs in (
        ("ws1", "app1", [("0.0.1", 0.2, "baseline"), ("0.0.2", 0.9, "other")]),
        ("ws2", "app2", [("0.0.3", 0.1, "Baseline two")]),
    ):
        root = tmp_path / ws
        (root / ".vmn").mkdir(parents=True)
        for verstr, loss, note in runs:
            _run(str(root), app, verstr, loss, note)
        manager.attach_path(ws, str(root))
    chain = AuthenticatorChain([_Fixed()]) if auth else None
    return TestClient(create_app(manager, auth=chain, **kw))


def _hits(response):
    assert response.status_code == 200, response.text
    return [(h["workspace"], h["app"], h["verstr"]) for h in response.json()["results"]]


def test_search_spans_workspaces(tmp_path):
    client = _client(tmp_path)
    hits = _hits(client.get(SEARCH, params={"q": "metrics.loss < 0.5"}))
    assert hits == [("ws1", "app1", "0.0.1"), ("ws2", "app2", "0.0.3")]
    body = client.get(SEARCH, params={"q": 'note ~ "baseline"'}).json()
    assert body["truncated"] is False
    assert body["results"][0]["row"]["metrics"]["loss"] == 0.2


def test_search_limit_truncates(tmp_path):
    body = _client(tmp_path).get(SEARCH, params={"q": "metrics.loss > 0", "limit": 1}).json()
    assert len(body["results"]) == 1 and body["truncated"] is True


def test_bad_query_is_a_400(tmp_path):
    response = _client(tmp_path).get(SEARCH, params={"q": "statuz = 1"})
    assert response.status_code == 400
    assert "statuz" in response.json()["detail"]


def test_search_only_sees_the_callers_workspaces(tmp_path):
    client = _client(tmp_path, auth=True)
    q = {"q": "metrics.loss < 0.5"}
    one = _hits(client.get(SEARCH, params=q, headers={"Authorization": "Bearer one"}))
    assert one == [("ws1", "app1", "0.0.1")]
    every = _hits(client.get(SEARCH, params=q, headers={"Authorization": "Bearer all"}))
    assert len(every) == 2
    refused = client.get(SEARCH, params=q, headers={"Authorization": "Bearer none"})
    assert refused.status_code == 403


def test_postgres_mode_answers_in_sql(tmp_path, pg_dsn, monkeypatch):  # noqa: F811
    from vmn_exp.ui.readers import experiments

    def no_python(*_a, **_k):
        raise AssertionError("Postgres mode must not filter in Python")

    client = _client(tmp_path, search_dsn=pg_dsn)
    monkeypatch.setattr(experiments, "filter_rows", no_python)
    hits = _hits(client.get(SEARCH, params={"q": 'note ~ "baseline" or metrics.loss > 0.5'}))
    assert hits == [("ws1", "app1", "0.0.1"), ("ws1", "app1", "0.0.2"), ("ws2", "app2", "0.0.3")]
    limited = client.get(SEARCH, params={"q": "metrics.loss > 0", "limit": 2}).json()
    assert len(limited["results"]) == 2 and limited["truncated"] is True
    assert client.get(SEARCH, params={"q": "statuz = 1"}).status_code == 400
