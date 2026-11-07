"""Plan 32 F10: a Jobs view page (``top=``, flat or grouped) and a tree page
(``children_of``) carry ``main``, the metric (and its goal) the server's job
rollups summarize, so the web never picks its own: the primary, else the
alphabetically first metric with a goal; a page without job rows too."""
import pytest

pytest.importorskip("fastapi")
from test_ui_leaderboard_groups_route import APP, _client, _conf, _record

BASE = f"/api/v1/workspaces/ws/apps/{APP}/experiments"


def _served(tmp_path, metrics):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    root = str(root)
    # 1 <- 2, 3; 4 alone
    runs = {n: _record(root, n, loss, parent) for n, loss, parent in [
        (1, 0.5, None), (2, 9.0, 1), (3, 1.0, 1), (4, 3.0, None)]}
    _conf(root, {"metrics": metrics})
    return _client(tmp_path, root), runs


def _get(client, **params):
    r = client.get(BASE, params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("params", [
    {"top": "1", "limit": 50}, {"top": "jobs", "limit": 50}, {"top": "singles", "limit": 50},
    {"top": "1", "group": "status"}, {"top": "1", "q": "metrics.loss < 5", "match_subtree": "1",
                                      "limit": 50}])
def test_a_jobs_page_names_the_alphabetically_first_goal_metric(tmp_path, params):
    client, _ = _served(tmp_path, {"zeta": {"goal": "max"}, "loss": {"goal": "min"}})
    assert _get(client, **params)["main"] == {"metric": "loss", "goal": "min"}


def test_the_primary_is_the_main_metric(tmp_path):
    client, _ = _served(tmp_path, {"loss": {"goal": "min"}, "acc": {"goal": "max",
                                                                     "primary": True}})
    assert _get(client, top="1", limit=50)["main"] == {"metric": "acc", "goal": "max"}


def test_a_tree_page_names_the_main_metric(tmp_path):
    client, runs = _served(tmp_path, {"zeta": {"goal": "max"}, "loss": {"goal": "min"}})
    assert _get(client, children_of=runs[1], limit=50)["main"] == {"metric": "loss",
                                                                     "goal": "min"}


def test_a_goal_less_main_metric_has_no_goal(tmp_path):
    client, _ = _served(tmp_path, {"loss": {"primary": True}})
    assert _get(client, top="1", limit=50)["main"] == {"metric": "loss", "goal": None}


def test_a_page_without_top_carries_no_main(tmp_path):
    client, _ = _served(tmp_path, {"loss": {"goal": "min"}})
    assert "main" not in _get(client, limit=50)
