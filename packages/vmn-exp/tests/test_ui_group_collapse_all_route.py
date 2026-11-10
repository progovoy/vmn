"""Plan 34 §1 over HTTP: ``collapse_all=1`` on a grouped Outer runs page answers
each group as its header alone (no rows), with its pooled aggregate and its
attempts' summed ``run_counts``; without ``group`` and ``top`` it is a 400."""
import pytest

pytest.importorskip("fastapi")
from test_ui_scope_route import BASE, served  # noqa: F401

# served: 1 <- 2, 3; 3 <- 4; 5 alone


def _get(client, status=200, **params):
    r = client.get(f"{BASE}/experiments", params=params)
    assert r.status_code == status, r.text
    return r


def test_a_collapsed_grouped_page_carries_headers_without_rows(served):  # noqa: F811
    client, _ = served
    (group,) = _get(client, group="status", top="jobs", collapse_all="1").json()["groups"]
    assert group["rows"] == [] and group["rows_total"] == 1
    assert group["job_aggregates"]["loss"]["n"] == 2
    assert sum(group["run_counts"].values()) == 3


def test_a_grouped_outer_runs_page_names_its_aggregate(served):  # noqa: F811
    client, _ = served
    page = _get(client, group="status", top="jobs", collapse_all="1", job_agg="median").json()
    assert (page["job_agg"]["agg"], page["job_agg"]["metric"]) == ("median", "loss")


def test_collapse_all_keys_the_etag(served):  # noqa: F811
    client, _ = served
    tags = {_get(client, group="status", top="jobs", **extra).headers["etag"]
            for extra in ({}, {"collapse_all": "1"})}
    assert len(tags) == 2


@pytest.mark.parametrize("params", [{"collapse_all": "1"}, {"collapse_all": "1", "group": "status"},
                                    {"collapse_all": "1", "top": "jobs"}])
def test_collapse_all_needs_a_grouped_outer_runs_page(served, params):  # noqa: F811
    client, _ = served
    assert "collapse_all" in _get(client, 400, **params).json()["detail"]
