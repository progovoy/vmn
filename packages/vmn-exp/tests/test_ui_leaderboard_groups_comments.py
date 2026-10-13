"""Plan 22 K1 with comments: grouped rows carry their comment counts, and a
query over ``comments`` cuts a grouping's rows like any other filter (G6)."""
import pytest

pytest.importorskip("fastapi")

from test_ui_experiment_query import _client, _seed, _url
from test_ui_report_index import _comment


def _grouped(client, app_layout, **params):
    resp = client.get(_url(app_layout), params={"group": "status", **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _rows(body):
    return {row["verstr"]: row for group in body["groups"] for row in group["rows"]}


def test_grouped_rows_carry_comment_counts(app_layout):
    _seed(app_layout)
    client = _client(app_layout)
    _comment(client, app_layout.app_name, "0.0.2")
    rows = _rows(_grouped(client, app_layout))
    assert rows["0.0.2"]["comments"] == {"total": 1, "unresolved": 1}
    assert "comments" not in rows["0.0.1"]


def test_a_comments_query_cuts_the_grouped_rows(app_layout):
    _seed(app_layout)
    client = _client(app_layout)
    _comment(client, app_layout.app_name, "0.0.4")
    body = _grouped(client, app_layout, q="comments.unresolved > 0")
    assert list(_rows(body)) == ["0.0.4"]
    assert body["total_rows"] == 1
    [group] = body["groups"]
    assert group["counts"]["total"] == 1
    one = client.get(_url(app_layout), params={
        "group": "status", "q": "comments.total >= 1", "group_key": group["key"]}).json()
    assert [row["verstr"] for row in one["rows"]] == ["0.0.4"]
    assert one["rows"][0]["comments"]["total"] == 1
