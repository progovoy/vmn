"""Plan 23 S8b over HTTP: ``GET .../experiments?top=1&match_subtree=1&q=``
keeps the jobs whose subtree matches, each with ``matched``, and answers
``jobs_matched``/``runs_matched``."""
import pytest

pytest.importorskip("fastapi")
from test_ui_search_index_route import APP, _verstr, client  # noqa: F401

URL = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def test_a_job_with_a_matching_inner_is_kept_with_its_count(client):  # noqa: F811
    body = client.get(URL, params={"top": 1, "match_subtree": 1, "q": 'note ~ "grid one"',
                                   "limit": 50}).json()
    assert [(r["verstr"], r["matched"]) for r in body["rows"]] == [(_verstr(1), 1)]
    assert (body["jobs_matched"], body["runs_matched"]) == (1, 1)


def test_match_subtree_without_top_is_a_400(client):  # noqa: F811
    r = client.get(URL, params={"match_subtree": 1, "q": 'name ~ "grid"', "limit": 50})
    assert r.status_code == 400


def test_the_etag_tells_match_subtree_apart(client):  # noqa: F811
    params = {"top": 1, "q": 'name ~ "t2"', "limit": 50}
    plain = client.get(URL, params=params)
    matched = client.get(URL, params=dict(params, match_subtree=1),
                         headers={"If-None-Match": plain.headers["etag"]})
    assert matched.status_code == 200
    assert plain.json()["rows"] == [] and matched.json()["runs_matched"] == 1
