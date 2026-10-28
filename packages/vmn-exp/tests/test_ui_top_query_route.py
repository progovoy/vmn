"""Plan 28 §4.5 over HTTP: ``GET .../experiments?top=1&top_q=`` keeps the
top-level runs passing ``top_q`` by their own fields; it is pinned like
``q``, in the ETag, and a 400 without ``top``."""
import pytest

pytest.importorskip("fastapi")
from test_ui_search_index_route import APP, _verstr, client  # noqa: F401

URL = f"/api/v1/workspaces/ws/apps/{APP}/experiments"
OUTERS = 'kind = "outer"'


def test_top_q_filters_the_outer_runs(client):  # noqa: F811
    body = client.get(URL, params={"top": 1, "top_q": OUTERS, "limit": 50}).json()
    assert [r["verstr"] for r in body["rows"]] == [_verstr(1)]


def test_top_q_with_match_subtree_keeps_the_preset_on_the_top_rows(client):  # noqa: F811
    params = {"top": 1, "match_subtree": 1, "q": 'name ~ "t2"', "top_q": OUTERS, "limit": 50}
    body = client.get(URL, params=params).json()
    assert [r["verstr"] for r in body["rows"]] == [_verstr(1)]


def test_top_q_with_ago_is_pinned(client):  # noqa: F811
    params = {"top": 1, "top_q": 'finished_at >= ago("6h")', "limit": 50}
    assert client.get(URL, params=params).status_code == 200


def test_the_etag_tells_top_q_apart(client):  # noqa: F811
    plain = client.get(URL, params={"top": 1, "limit": 50})
    top_q = client.get(URL, params={"top": 1, "top_q": OUTERS, "limit": 50},
                       headers={"If-None-Match": plain.headers["etag"]})
    assert top_q.status_code == 200


def test_top_q_without_top_is_a_400(client):  # noqa: F811
    assert client.get(URL, params={"top_q": OUTERS, "limit": 50}).status_code == 400


def test_a_bad_top_q_is_a_400(client):  # noqa: F811
    assert client.get(URL, params={"top": 1, "top_q": "kind =", "limit": 50}).status_code == 400


def test_grouped_top_q(client):  # noqa: F811
    body = client.get(URL, params={"top": 1, "top_q": OUTERS, "group": "status"}).json()
    assert sum(g["rows_total"] for g in body["groups"]) == 1
