"""``GET .../experiments/{verstr}/baselines`` (plan 20 K3): the runs the
Changes card can diff a run against, from the index snapshot."""
import pytest
from run_code_seed import API, client, finished_state, metrics, run_url, seed_run

pytest.importorskip("fastapi")

TRAIN = ("python", "train.py")
EVAL = ("python", "eval.py")
LOSS_GOAL = {"type": "define_metric", "name": "loss", "goal": "min"}


def _baselines(app_layout, verstr):
    resp = client(app_layout).get(run_url(app_layout, verstr, "/baselines"))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _idx(app_layout):
    rows = client(app_layout).get(f"{API}/{app_layout.app_name}/experiments").json()
    return {row["verstr"]: row["idx"] for row in rows}


def _seed_fleet(app_layout, goal=True):
    declared = [LOSS_GOAL] if goal else []
    seed_run(app_layout, "0.0.1-dev.r1", 1, finished_state(0, TRAIN), name="good",
             entries=declared + [metrics({"loss": 0.2})])
    seed_run(app_layout, "0.0.1-dev.r2", 2, finished_state(0, EVAL),
             entries=[metrics({"loss": 0.1})])
    seed_run(app_layout, "0.0.1-dev.r3", 3, finished_state(0, TRAIN), branch="other",
             entries=[metrics({"loss": 0.3})])
    seed_run(app_layout, "0.0.1-dev.r4", 4, finished_state(1, TRAIN), name="broken",
             has_working_tree_patch=True, entries=declared + [metrics({"loss": 0.9})])


def test_previous_is_the_latest_earlier_run_of_the_same_branch_and_command(app_layout):
    _seed_fleet(app_layout)
    body = _baselines(app_layout, "0.0.1-dev.r4")
    assert body["previous"] == {
        "verstr": "0.0.1-dev.r1", "idx": _idx(app_layout)["0.0.1-dev.r1"],
        "name": "good", "status": "succeeded",
    }


def test_base_is_the_run_itself_when_it_has_a_patch(app_layout):
    _seed_fleet(app_layout)
    body = _baselines(app_layout, "0.0.1-dev.r4")
    assert body["base"] == {
        "verstr": "0.0.1-dev.r4", "idx": _idx(app_layout)["0.0.1-dev.r4"],
        "name": "broken", "status": "failed",
    }
    assert "base" not in _baselines(app_layout, "0.0.1-dev.r1")


def test_best_is_the_best_other_run_on_the_declared_goal(app_layout):
    _seed_fleet(app_layout)
    body = _baselines(app_layout, "0.0.1-dev.r4")
    assert body["best"]["verstr"] == "0.0.1-dev.r2"
    assert _baselines(app_layout, "0.0.1-dev.r2")["best"]["verstr"] == "0.0.1-dev.r1"


def test_best_is_absent_without_a_declared_goal(app_layout):
    _seed_fleet(app_layout, goal=False)
    assert "best" not in _baselines(app_layout, "0.0.1-dev.r4")


def test_the_first_run_has_no_previous(app_layout):
    _seed_fleet(app_layout)
    assert "previous" not in _baselines(app_layout, "0.0.1-dev.r1")


def test_parent_fork_and_rerun_origins(app_layout):
    _seed_fleet(app_layout)
    seed_run(app_layout, "0.0.1-dev.r5", 5, finished_state(0, TRAIN),
             parent="0.0.1-dev.r2", forked_from={"verstr": "0.0.1-dev.r1", "step": 3},
             rerun_of="0.0.1-dev.r3")
    body = _baselines(app_layout, "0.0.1-dev.r5")
    assert body["parent"]["verstr"] == "0.0.1-dev.r2"
    assert body["forked_from"]["verstr"] == "0.0.1-dev.r1"
    assert body["rerun_of"]["verstr"] == "0.0.1-dev.r3"
    assert body["rerun_of"]["status"] == "succeeded"


def test_an_origin_missing_from_the_index_is_left_out(app_layout):
    seed_run(app_layout, "0.0.1-dev.r1", 1, finished_state(0, TRAIN), rerun_of="0.0.1-dev.gone")
    assert _baselines(app_layout, "0.0.1-dev.r1") == {}


def test_an_unknown_run_is_404(app_layout):
    _seed_fleet(app_layout)
    resp = client(app_layout).get(run_url(app_layout, "0.0.1-dev.nope", "/baselines"))
    assert resp.status_code == 404


def test_the_etag_repeats(app_layout):
    _seed_fleet(app_layout)
    api = client(app_layout)
    url = run_url(app_layout, "0.0.1-dev.r4", "/baselines")
    etag = api.get(url).headers["etag"]
    assert api.get(url, headers={"If-None-Match": etag}).status_code == 304
