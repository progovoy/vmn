"""Plan 23 S7 over HTTP: ``top=jobs|singles``, the facets' ``jobs``/``singles``,
a grouped Jobs view's job fields and every group's ``clause``."""
import pytest

pytest.importorskip("fastapi")
from test_ui_scope_route import BASE, served  # noqa: F401

# served: 1 <- 2, 3; 3 <- 4; 5 alone


def _get(client, path="experiments", **params):
    r = client.get(f"{BASE}/{path}", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _verstrs(body):
    return {r["verstr"] for r in body["rows"]}


def test_top_jobs_and_singles_split_the_top_level_runs(served):  # noqa: F811
    client, runs = served
    assert _verstrs(_get(client, top="jobs", limit=50)) == {runs[1]}
    assert _verstrs(_get(client, top="singles", limit=50)) == {runs[5]}
    assert _verstrs(_get(client, top="1", limit=50)) == {runs[1], runs[5]}
    assert _verstrs(_get(client, top="true", limit=50)) == {runs[1], runs[5]}


def test_an_unknown_top_is_400(served):  # noqa: F811
    client, _ = served
    assert client.get(f"{BASE}/experiments", params={"top": "outers"}).status_code == 400


def test_the_etag_follows_top(served):  # noqa: F811
    client, _ = served
    tags = {client.get(f"{BASE}/experiments", params={"top": t, "limit": 5}).headers["etag"]
            for t in ("jobs", "singles", "1")}
    assert len(tags) == 3


def test_facets_count_jobs_and_singles(served):  # noqa: F811
    client, _ = served
    body = _get(client, "experiments-facets")
    assert (body["jobs"], body["singles"]) == (1, 1)


def test_a_grouped_jobs_view_carries_job_fields_and_clauses(served):  # noqa: F811
    client, runs = served
    body = _get(client, group="status", top="jobs")
    (group,) = body["groups"]
    assert group["job_counts"]["total"] == 1
    assert group["runs"] == 3
    assert group["job_aggregates"]["loss"]["n"] == 1
    assert group["clause"] == 'status = "succeeded"'
    flat = _get(client, q=group["clause"], top="jobs", limit=50)
    assert _verstrs(flat) == {runs[1]}


def test_group_parent_without_top_is_still_served(served):  # noqa: F811
    client, runs = served
    body = _get(client, group="parent")
    assert runs[1] in [g["key"] for g in body["groups"]]
    assert "job_counts" not in body["groups"][0]
