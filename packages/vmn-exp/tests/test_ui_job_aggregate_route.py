"""Plan 31 §2 over HTTP: ``…/experiments?top=1&job_agg=…&job_agg_by=…&
job_agg_value=…&job_agg_metric=…`` puts ``rolled`` on each Jobs row's
``job``, sorts it with ``job:value``, refuses a bad value or one without
``top``, keys the ETag by it, and defaults to the app's
``experiment.ui.job_aggregate``."""
import pytest

pytest.importorskip("fastapi")
from test_ui_leaderboard_groups_route import APP, _client, _conf, _record

BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _served(tmp_path, ui=None):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    # job 1: children 0.9, 0.5, 0.1 (median 0.5); job 5: 0.4, 0.3 (median 0.35); 8 alone
    runs = {n: _record(root, n, loss, parent) for n, loss, parent in [
        (1, 9.0, None), (2, 0.9, 1), (3, 0.5, 1), (4, 0.1, 1),
        (5, 9.0, None), (6, 0.4, 5), (7, 0.3, 5), (8, 2.0, None)]}
    experiment = {"metrics": {"loss": {"goal": "min"}}}
    if ui:
        experiment["ui"] = ui
    _conf(root, experiment)
    return _client(tmp_path, root), runs


def _get(client, status=200, **params):
    r = client.get(BASE, params=params)
    assert r.status_code == status, r.text
    return r


def _rolled(client, **params):
    rows = _get(client, top="1", limit=50, **params).json()["rows"]
    return {row["verstr"]: (row["job"] or {}).get("rolled") for row in rows}


def test_each_jobs_row_carries_its_rolled_aggregate(tmp_path):
    client, runs = _served(tmp_path)
    default = _rolled(client)
    assert default[runs[1]]["agg"] == "best" and default[runs[1]]["value"] == 0.1
    assert default[runs[8]] is None  # a single run has no job
    median = _rolled(client, job_agg="median")
    assert median[runs[1]] == {
        "agg": "median", "by": "children", "source": "best", "metric": "loss", "goal": "min",
        "percentile": None, "value": 0.5, "n": 3, "of": 3, "conflicts": 0,
        "verstr": runs[3], "approx": False}
    assert median[runs[5]]["value"] == pytest.approx(0.35)
    assert _rolled(client, job_agg="best10", job_agg_value="own",
                   job_agg_metric="loss")[runs[1]]["percentile"] == "p10"


def test_job_value_sorts_best_first_by_the_goal(tmp_path):
    client, runs = _served(tmp_path)
    rows = _get(client, top="1", limit=50, sort="job:value", job_agg="median").json()["rows"]
    assert [r["verstr"] for r in rows] == [runs[5], runs[1], runs[8]]
    rows = _get(client, top="1", limit=50, sort="job:value", job_agg="max").json()["rows"]
    assert [r["verstr"] for r in rows] == [runs[5], runs[1], runs[8]]
    rows = _get(client, top="1", limit=50, sort="job:value", job_agg="min").json()["rows"]
    assert [r["verstr"] for r in rows] == [runs[1], runs[5], runs[8]]


@pytest.mark.parametrize("params", [
    {"top": "1", "job_agg": "sum"}, {"top": "1", "job_agg_by": "depth:2"},
    {"top": "1", "job_agg_value": "last"}, {"top": "1", "job_agg_metric": ""},
    {"job_agg": "median"}, {"job_agg_by": "runs"}])
def test_a_bad_value_or_one_without_top_is_refused(tmp_path, params):
    client, _ = _served(tmp_path)
    _get(client, status=400, **params)


def test_a_tree_page_refuses_it(tmp_path):
    client, runs = _served(tmp_path)
    _get(client, status=400, children_of=runs[1], job_agg="median")


def test_the_etag_follows_the_aggregate(tmp_path):
    client, _ = _served(tmp_path)
    tags = {_get(client, top="1", **p).headers["etag"]
            for p in ({}, {"job_agg": "median"}, {"job_agg_by": "runs"},
                      {"job_agg_value": "own"}, {"job_agg_metric": "loss"})}
    assert len(tags) == 5
    again = _get(client, top="1", job_agg="median").headers["etag"]
    assert again in tags


def test_the_apps_setting_is_the_default_and_the_url_overrides_it(tmp_path):
    client, runs = _served(tmp_path, {"job_aggregate": {"agg": "median", "value": "own"}})
    assert _rolled(client)[runs[1]]["agg"] == "median"
    assert _rolled(client)[runs[1]]["source"] == "own"
    got = _rolled(client, job_agg="max")[runs[1]]
    assert (got["agg"], got["source"], got["value"]) == ("max", "own", 0.9)


def test_a_grouped_jobs_view_aggregates_the_rolled_values(tmp_path):
    client, runs = _served(tmp_path)
    body = _get(client, top="jobs", group="status", job_agg="median").json()
    loss = body["groups"][0]["job_aggregates"]["loss"]
    # pooled: the children of jobs 1 and 5
    assert loss["n"] == 5 and loss["mean"] == pytest.approx((0.9 + 0.5 + 0.1 + 0.4 + 0.3) / 5)
    assert loss["value"] == pytest.approx(0.4)
