"""The list route's ETag (and the encoded-body cache key) is built from what
it hands ``cache.etag``: for fixed requests that must stay the same across
refactors of how the route reads its parameters (plan 42 E12d). The real
ETag carries a per-process nonce, so the guard pins its inputs."""
import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from fakes.clock import FakeClock  # noqa: E402
from vmn_exp.ui import routes_leaderboard  # noqa: E402
from vmn_exp.ui.query_params import refuse_unknown_params  # noqa: E402

API = "/api/v1"
BASE = f"{API}/workspaces/ws/apps/my_app/experiments"
RUN = "0.0.1-dev.0000abcd.0"


class FakeSnapshot:
    loading = None


class FakeJobs:
    def main(self, snapshot, schema):
        return None


class FakeCache:
    max_page = 1000

    def __init__(self):
        self.etags = []
        self.jobs = FakeJobs()

    def now(self):
        return FakeClock().now()

    def etag(self, snapshot, schema, **params):
        self.etags.append(params)
        return f"e{len(self.etags)}"

    def page(self, snapshot, schema, **params):
        return {"rows": [], "total": 1}

    def groups(self, snapshot, schema, group, **params):
        return {"groups": [], "total": 1}


def _etag_inputs(params):
    cache = FakeCache()
    app = FastAPI(dependencies=[refuse_unknown_params(API)])
    routes_leaderboard.register(app, API, lambda ws, tag: (FakeSnapshot(), {}), cache)
    response = TestClient(app).get(BASE, params=params)
    assert response.status_code == 200, response.text
    (given,) = cache.etags
    return {k: (v if k != "job_agg" else str(v)) for k, v in given.items() if k != "minute"}, given


FLAT = dict(offset=5, limit=10, sort="loss", status="running", query=None, order="desc",
            archived=True, scope=None, top=False, top_query=None, last=None, cursor=None,
            comments=0, match_subtree=False, attention=())


def test_a_flat_page_hands_the_same_etag_inputs():
    params = {"offset": "5", "limit": "10", "sort": "loss", "status": "running",
              "order": "desc", "archived": "1"}
    assert _etag_inputs(params)[0] == FLAT


def test_a_grouped_page_hands_the_same_etag_inputs():
    given, _ = _etag_inputs({"group": "parent", "rows_per_group": "3", "agg": "best"})
    assert given == dict(offset=0, limit=50, sort=None, status=None, query=None, order=None,
                         archived=False, scope=None, top=False, top_query=None, agg="best",
                         rows_per_group=3, group_key=None, comments=0, group="parent")


def test_a_collapsed_jobs_group_hands_the_same_etag_inputs():
    given, raw = _etag_inputs({"group": "parent", "top": "jobs", "collapse_all": "1",
                               "job_agg_nested": "1"})
    assert "minute" in raw
    assert given == dict(offset=0, limit=50, sort=None, status=None, query=None, order=None,
                         archived=False, scope=None, top="jobs", top_query=None,
                         job_agg=given["job_agg"], agg="mean", rows_per_group=0,
                         group_key=None, comments=0, group="parent")
    assert "nested=True" in given["job_agg"]


def test_a_tree_page_hands_the_same_etag_inputs():
    given, raw = _etag_inputs({"children_of": RUN, "limit": "20", "match_subtree": "1"})
    assert "minute" in raw
    assert given == dict(offset=0, limit=20, sort=None, status=None, query=None, order=None,
                         archived=False, scope=None, top=False, top_query=None, last=None,
                         cursor=None, children_of=RUN, match_subtree=True, attention=(),
                         split=None, tree_columns={}, comments=0)
