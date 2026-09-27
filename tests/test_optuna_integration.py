"""Tests for the Optuna integration: start_study_run + tracker.wrap().

TDD: these tests define the required behaviour before implementation exists.
Run with:
  python -m pytest tests/test_optuna_integration.py -x -q
"""
import os

import pytest

optuna = pytest.importorskip("optuna")

from helpers import _bootstrap, _storage  # noqa: E402
from vmn_exp.integrations.optuna_study import start_study_run  # noqa: E402
from vmn_exp.sdk.reader import list_runs  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def _rows(app_layout):
    """All run rows for the app."""
    storage = _storage(app_layout)
    return list_runs(app_layout.app_name, storage=storage, use_index=False)


# ---------------------------------------------------------------------------
# 1. Study outer run + trial inner runs linked via parent
# ---------------------------------------------------------------------------

def test_study_outer_run_and_trial_inner_runs_linked(app_layout):
    """start_study_run opens an outer run; each trial becomes an inner run."""
    _bootstrap(app_layout)

    def objective(trial):
        x = trial.suggest_float("x", -5.0, 5.0)
        return x ** 2

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=3)
    tracker.finish()

    rows = _rows(app_layout)
    outer = [r for r in rows if r.get("parent") is None]
    inner = [r for r in rows if r.get("parent") is not None]

    assert len(outer) == 1, f"Expected 1 outer run, got {len(outer)}"
    assert len(inner) == 3, f"Expected 3 inner runs, got {len(inner)}"
    outer_id = outer[0]["verstr"]
    for r in inner:
        assert r["parent"] == outer_id


# ---------------------------------------------------------------------------
# 2. Params and metrics per trial
# ---------------------------------------------------------------------------

def test_params_metrics_per_trial(app_layout):
    """Each trial run records its params and the objective return value."""
    _bootstrap(app_layout)

    def objective(trial):
        lr = trial.suggest_float("lr", 1e-4, 1e-1, log=True)
        return lr * 2.0  # deterministic result for assertion

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=2)
    tracker.finish()

    rows = _rows(app_layout)
    inner = [r for r in rows if r.get("parent") is not None]
    assert len(inner) == 2

    for r in inner:
        assert "lr" in r.get("params", {}), "trial param 'lr' must be recorded"
        assert "objective" in r.get("metrics", {}), "return value must be recorded as 'objective'"


# ---------------------------------------------------------------------------
# 3. n_jobs=4 (thread-pool): all trials nest under the study
# ---------------------------------------------------------------------------

def test_trials_nest_under_study_n_jobs_threads(app_layout):
    """With n_jobs=4 trials run in threads; all still nest under the outer run."""
    _bootstrap(app_layout)

    def objective(trial):
        x = trial.suggest_float("x", 0.0, 1.0)
        return x

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=4, n_jobs=4)
    tracker.finish()

    rows = _rows(app_layout)
    outer = [r for r in rows if r.get("parent") is None]
    inner = [r for r in rows if r.get("parent") is not None]

    assert len(outer) == 1
    assert len(inner) == 4
    outer_id = outer[0]["verstr"]
    for r in inner:
        assert r["parent"] == outer_id


# ---------------------------------------------------------------------------
# 4. Pruned trial: tagged state=pruned, recorded as succeeded, series intact
# ---------------------------------------------------------------------------

def test_pruned_trial_tagged_succeeded_with_series(app_layout):
    """A pruned trial records as succeeded with state=pruned and its series."""
    _bootstrap(app_layout)

    def objective(trial):
        for step in range(3):
            trial.report(float(step), step)
            if step == 1:
                raise optuna.TrialPruned()
        return 0.0

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=1)
    tracker.finish()

    rows = _rows(app_layout)
    inner = [r for r in rows if r.get("parent") is not None]
    assert len(inner) == 1
    r = inner[0]
    assert r["status"] == "succeeded", f"Pruned trial must be succeeded, got {r['status']}"
    assert r.get("tags", {}).get("state") == "pruned"
    # Intermediate values reported via trial.report must land as a series
    assert "intermediate" in r.get("metrics", {}), (
        "intermediate values must be logged as a metric"
    )


# ---------------------------------------------------------------------------
# 5. Failed trial: recorded failed, study continues
# ---------------------------------------------------------------------------

def test_failed_trial_recorded_failed_and_study_continues(app_layout):
    """A trial that raises a non-pruned exception records as failed; study goes on."""
    _bootstrap(app_layout)

    call_count = {"n": 0}

    def objective(trial):
        call_count["n"] += 1
        x = trial.suggest_float("x", 0.0, 1.0)
        if call_count["n"] == 1:
            raise ValueError("deliberate failure")
        return x

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    # catch=(ValueError,) tells Optuna to mark failed trials and continue
    study.optimize(tracker.wrap(objective), n_trials=2, catch=(ValueError,))
    tracker.finish()

    rows = _rows(app_layout)
    inner = [r for r in rows if r.get("parent") is not None]
    assert len(inner) == 2
    statuses = {r["status"] for r in inner}
    assert "failed" in statuses
    assert "succeeded" in statuses


# ---------------------------------------------------------------------------
# 6. Multi-objective: keys are objective_0, objective_1, ...
# ---------------------------------------------------------------------------

def test_multi_objective_keys(app_layout):
    """Multi-objective study records values as objective_0, objective_1, ..."""
    _bootstrap(app_layout)

    def objective(trial):
        x = trial.suggest_float("x", 0.0, 1.0)
        return x, 1.0 - x

    study = optuna.create_study(directions=["minimize", "maximize"])
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=2)
    tracker.finish()

    rows = _rows(app_layout)
    inner = [r for r in rows if r.get("parent") is not None]
    assert len(inner) == 2
    for r in inner:
        metrics = r.get("metrics", {})
        assert "objective_0" in metrics, "first objective must be objective_0"
        assert "objective_1" in metrics, "second objective must be objective_1"


# ---------------------------------------------------------------------------
# 7. Best value/params logged on the outer run after finish()
# ---------------------------------------------------------------------------

def test_best_logged_on_outer(app_layout):
    """tracker.finish() logs the best trial's value and params on the outer run."""
    _bootstrap(app_layout)

    def objective(trial):
        x = trial.suggest_float("x", -5.0, 5.0)
        return x ** 2

    study = optuna.create_study(direction="minimize")
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=4)
    tracker.finish()

    rows = _rows(app_layout)
    outer = [r for r in rows if r.get("parent") is None]
    assert len(outer) == 1
    outer_row = outer[0]
    # best_value and at least one best_param must appear
    metrics = outer_row.get("metrics", {})
    params = outer_row.get("params", {})
    assert "best_value" in metrics, f"best_value missing from outer metrics: {metrics}"
    assert any(k.startswith("best_") for k in params), (
        f"no best_* params on outer run: {params}"
    )


# ---------------------------------------------------------------------------
# 8. autolog() inside objective lands in the trial run (current_run = trial)
# ---------------------------------------------------------------------------

def test_autolog_in_objective_lands_in_trial(app_layout):
    """autolog() inside the objective records into the trial's run via current_run."""
    sklearn = pytest.importorskip("sklearn")
    from sklearn.linear_model import LinearRegression
    import numpy as np
    from vmn_exp.sdk import autolog, autolog_disable, current_run

    _bootstrap(app_layout)

    collected = []

    def objective(trial):
        autolog()
        cr = current_run()
        assert cr is not None, "current_run() must return the trial run inside objective"
        collected.append(cr.id)
        # Fit a tiny model — autolog should log params into cr
        X = np.array([[1.0], [2.0], [3.0]])
        y = np.array([1.0, 2.0, 3.0])
        LinearRegression().fit(X, y)
        autolog_disable()
        return 0.0

    study = optuna.create_study()
    tracker = start_study_run(study, app_name=app_layout.app_name)
    study.optimize(tracker.wrap(objective), n_trials=1)
    tracker.finish()

    assert len(collected) == 1, "objective must have run once"
    trial_id = collected[0]
    rows = _rows(app_layout)
    trial_row = next((r for r in rows if r["verstr"] == trial_id), None)
    assert trial_row is not None
    params = trial_row.get("params", {})
    # autolog sklearn should have recorded sklearn_estimator
    assert any("sklearn" in k for k in params), (
        f"autolog params not found in trial run: {params}"
    )
