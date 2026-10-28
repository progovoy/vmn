"""``vmn-exp sweep`` declares its metric's goal (plan 28 follow-up): the
outer run and each trial carry a ``define_metric`` with the spec's
``metric.goal``, so a store workspace without conf.yml ranks the sweep's
metric the right way round (as the Optuna tracker does)."""
import pytest

from exp_helpers import _storage
from test_sweep_cli import _clean_env, _create, _trials, _vmn_exp  # noqa: F401
from vmn_exp.sdk.reader import list_runs


def _goals(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return {e["name"]: e.get("goal") for e in log if e.get("type") == "define_metric"}


@pytest.mark.parametrize("spec_goal, goal", [("minimize", "min"), ("maximize", "max")])
def test_the_sweep_and_its_trials_declare_the_metrics_goal(app_layout, tmp_path, capsys,
                                                           spec_goal, goal):
    sweep = _create(app_layout, tmp_path, capsys, run_cap=2,
                    metric={"name": "loss", "goal": spec_goal})
    assert _goals(app_layout, sweep) == {"loss": goal}
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    trials = _trials(app_layout, sweep)
    assert len(trials) == 2
    for trial in trials:
        assert _goals(app_layout, trial["verstr"]) == {"loss": goal}


def test_ranking_follows_the_declared_goal(app_layout, tmp_path, capsys):
    sweep = _create(app_layout, tmp_path, capsys, metric={"name": "loss", "goal": "maximize"})
    assert _vmn_exp("sweep", "agent", app_layout.app_name, sweep) == 0
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout), sort="loss",
                     query=f'parent = "{sweep}"', use_index=False)
    assert [r["params"]["x"] for r in rows] == [3, 2, 1]
