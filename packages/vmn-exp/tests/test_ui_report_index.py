"""Plan 13 §8.2: the report index behind /reports, 'reports using this
app/run', and comment counts joined into leaderboard rows."""
import pytest

pytest.importorskip("fastapi")

from test_ui_experiment_query import _client, _seed, _url, _verstrs

WS = "/api/v1/workspaces/main"


def _panel(app, verstrs=None):
    runs = f"{{verstrs: [{', '.join(verstrs)}]}}" if verstrs else "{query: 'status = failed'}"
    return f"```vmn-panel\nv: 1\nid: p\ntype: curves\napp: {app}\nruns: {runs}\n```\n"


def _report(client, body, title="T"):
    r = client.post(f"{WS}/reports", json={"title": title, "body": body})
    assert r.status_code == 201, r.text
    return r.json()["rid"]


def _comment(client, app, verstr, text="hi", **extra):
    r = client.post(f"{WS}/comments", json={"target": f"run:{app}:{verstr}", "text": text, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _using(client, app, verstr=None):
    params = {"verstr": verstr} if verstr else {}
    r = client.get(f"{WS}/apps/{app}/reports", params=params)
    assert r.status_code == 200, r.text
    return [row["rid"] for row in r.json()["reports"]]


def test_reports_using_app_and_run(app_layout):
    client = _client(app_layout)
    app = app_layout.app_name
    pinned = _report(client, _panel(app, ["0.0.2"]))
    query = _report(client, _panel(app))
    _report(client, _panel("elsewhere", ["0.0.2"]))
    assert _using(client, app) == sorted([pinned, query])
    assert _using(client, app, "0.0.2") == sorted([pinned, query])
    assert _using(client, app, "0.0.3") == [query]


def test_reports_list_reflects_new_revision(app_layout):
    client = _client(app_layout)
    rid = _report(client, "", title="Old")
    assert client.patch(f"{WS}/reports/{rid}", json={"title": "New"}).status_code == 200
    [row] = client.get(f"{WS}/reports").json()["reports"]
    assert row["title"] == "New" and "body" not in row


def test_leaderboard_rows_carry_comment_counts(app_layout):
    _seed(app_layout)
    client = _client(app_layout)
    app = app_layout.app_name
    first = _comment(client, app, "0.0.2")
    _comment(client, app, "0.0.2", "re", reply_to=first)
    resolved = _comment(client, app, "0.0.3")
    r = client.patch(f"{WS}/comments/run:{app}:0.0.3/{resolved}", json={"resolved": True})
    assert r.status_code == 200, r.text
    rows = {row["verstr"]: row for row in client.get(_url(app_layout)).json()}
    assert rows["0.0.2"]["comments"] == {"total": 2, "unresolved": 1}
    assert rows["0.0.3"]["comments"] == {"total": 1, "unresolved": 0}
    assert "comments" not in rows["0.0.1"]


def test_query_on_unresolved_comments(app_layout):
    _seed(app_layout)
    client = _client(app_layout)
    app = app_layout.app_name
    _comment(client, app, "0.0.4")
    resp = client.get(_url(app_layout), params={"q": "comments.unresolved > 0"})
    assert resp.status_code == 200, resp.text
    assert _verstrs(resp) == ["0.0.4"]
    paged = client.get(_url(app_layout), params={"q": "comments.total >= 1", "limit": 10}).json()
    assert paged["total"] == 1 and paged["rows"][0]["comments"]["unresolved"] == 1


def test_new_comment_changes_the_etag(app_layout):
    _seed(app_layout)
    client = _client(app_layout)
    etag = client.get(_url(app_layout)).headers["etag"]
    _comment(client, app_layout.app_name, "0.0.1")
    resp = client.get(_url(app_layout), headers={"If-None-Match": etag})
    assert resp.status_code == 200
    assert {r["verstr"]: r.get("comments") for r in resp.json()}["0.0.1"]["total"] == 1
