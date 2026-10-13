"""Plan 23 S2 over HTTP: ``scope=`` on the list (flat and grouped), columns,
facets (with ``q``/``status``) and importance; ``top=1`` with ``job`` on
the rows and ``job:*`` sorts. An unknown scope is a 404."""
import pytest

pytest.importorskip("fastapi")
from test_ui_leaderboard_groups_route import APP, _client, _conf, _record

BASE = f"/api/v1/workspaces/ws/apps/{APP}"


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    # 1 <- 2, 3; 3 <- 4; 5 alone
    runs = {n: _record(root, n, loss, parent) for n, loss, parent in [
        (1, 0.5, None), (2, 9.0, 1), (3, 1.0, 1), (4, 2.0, 3), (5, 3.0, None)]}
    _conf(root, {"metrics": {"loss": {"goal": "min"}}})
    return _client(tmp_path, root), runs


def _verstrs(body):
    return {r["verstr"] for r in body["rows"]}


def test_scope_is_the_subtree_without_the_run(served):
    client, runs = served
    body = client.get(f"{BASE}/experiments", params={"scope": runs[1], "limit": 50}).json()
    assert _verstrs(body) == {runs[2], runs[3], runs[4]} and body["total"] == 3
    body = client.get(f"{BASE}/experiments", params={"scope": runs[3], "limit": 50}).json()
    assert _verstrs(body) == {runs[4]}
    assert {r["root"] for r in body["rows"]} == {runs[1]}


def test_an_unknown_scope_is_404_and_a_bad_one_400(served):
    client, _ = served
    for path in ("experiments", "experiments-columns", "experiments-facets"):
        assert client.get(f"{BASE}/{path}", params={"scope": "0.0.1-dev.nope"}).status_code == 404
    r = client.get(f"{BASE}/experiments-importance",
                   params={"scope": "0.0.1-dev.nope", "metric": "loss"})
    assert r.status_code == 404
    assert client.get(f"{BASE}/experiments", params={"scope": "a/../b"}).status_code == 400
    r = client.get(f"{BASE}/experiments", params={"scope": "0.0.1-dev.nope", "group": "parent"})
    assert r.status_code == 404


def test_grouped_columns_and_facets_follow_the_scope(served):
    client, runs = served
    body = client.get(f"{BASE}/experiments", params={"scope": runs[1], "group": "parent"}).json()
    assert body["total_rows"] == 3
    cols = client.get(f"{BASE}/experiments-columns",
                      params={"scope": runs[1], "keys": "metrics.loss"}).json()
    assert cols["total"] == 3
    facets = client.get(f"{BASE}/experiments-facets", params={"scope": runs[1]}).json()
    assert facets["total"] == 3 and facets["parented"] == 3
    facets = client.get(f"{BASE}/experiments-facets",
                        params={"scope": runs[1], "q": "metrics.loss < 5"}).json()
    assert facets["total"] == 2
    facets = client.get(f"{BASE}/experiments-facets", params={"status": "failed"}).json()
    assert facets["total"] == 0


def test_top_lists_jobs_with_their_summary(served):
    client, runs = served
    body = client.get(f"{BASE}/experiments", params={"top": 1, "limit": 50}).json()
    rows = {r["verstr"]: r for r in body["rows"]}
    assert set(rows) == {runs[1], runs[5]}
    assert rows[runs[1]]["job"]["total"] == 3
    assert rows[runs[1]]["job"]["best_idx"] == 3  # loss 1.0, run 3
    assert rows[runs[5]]["job"] is None
    body = client.get(f"{BASE}/experiments",
                      params={"top": 1, "limit": 50, "sort": "job:failed_pct"}).json()
    assert [r["verstr"] for r in body["rows"]] == [runs[1], runs[5]]


def test_a_job_sort_needs_top(served):
    client, _ = served
    r = client.get(f"{BASE}/experiments", params={"sort": "job:progress", "limit": 5})
    assert r.status_code == 400


def test_under_in_q_filters_like_scope(served):
    client, runs = served
    body = client.get(f"{BASE}/experiments",
                      params={"q": f'under("{runs[3]}")', "limit": 50}).json()
    assert _verstrs(body) == {runs[4]}
