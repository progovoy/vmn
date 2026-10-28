"""The Optuna tracker declares the goals of what it logs (plan 28 §5 Q3).

``best_value`` on the outer run and ``objective`` on each trial follow the
study's direction, so a store workspace without conf.yml ranks them the right
way round.
"""
import os

import pytest

optuna = pytest.importorskip("optuna")

from exp_helpers import _bootstrap, _storage  # noqa: E402
from vmn_exp.integrations.optuna_study import start_study_run  # noqa: E402
from vmn_exp.sdk.reader import list_runs  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def _goals(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return {e["name"]: e.get("goal") for e in log if e.get("type") == "define_metric"}


def _study(app_layout, objective, **create):
    _bootstrap(app_layout)
    study = optuna.create_study(**create)
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=2)
    tracker.finish()
    rows = list_runs(app_layout.app_name, storage=_storage(app_layout), use_index=False)
    outer = next(r["verstr"] for r in rows if r.get("parent") is None)
    inner = [r["verstr"] for r in rows if r.get("parent") is not None]
    return outer, inner


def _single(trial):
    return trial.suggest_float("x", 0.0, 1.0)


def _pair(trial):
    x = trial.suggest_float("x", 0.0, 1.0)
    return x, 1.0 - x


@pytest.mark.parametrize("direction, goal", [("minimize", "min"), ("maximize", "max")])
def test_best_value_and_objective_carry_the_study_direction(app_layout, direction, goal):
    outer, inner = _study(app_layout, _single, direction=direction)
    assert _goals(app_layout, outer) == {"best_value": goal}
    for verstr in inner:
        assert _goals(app_layout, verstr) == {"objective": goal}


def test_multi_objective_trials_declare_each_direction(app_layout):
    _, inner = _study(app_layout, _pair, directions=["minimize", "maximize"])
    for verstr in inner:
        assert _goals(app_layout, verstr) == {"objective_0": "min", "objective_1": "max"}
