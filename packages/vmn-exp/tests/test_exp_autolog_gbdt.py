"""LightGBM and CatBoost autolog (plan 43 F16), on fakes only.

A counterfeit ``lightgbm`` / ``catboost`` module is injected into
``sys.modules`` with small estimator classes shaped like the libraries'
scikit-learn API, and a FakeRun sits on the SDK's open-run stack. No real
library is imported here; test_exp_autolog_real.py checks the shapes against
the real ones.
"""
import os
import sys
import types

import pytest

from vmn_exp.sdk import autolog, autolog_disable
from vmn_exp.sdk import run as run_module

_ROOTS = ("lightgbm", "catboost")


class FakeLGBMRegressor:
    def __init__(self, evals=None, best_iteration=0):
        self._evals = evals
        self.best_iteration_ = best_iteration

    def get_params(self, deep=True):
        return {"n_estimators": 3, "learning_rate": 0.1}

    def fit(self, X, y=None, eval_set=None):
        self.evals_result_ = self._evals or {}
        self.best_score_ = {"valid_0": {"l2": 1.0}}
        return self

    def score(self, X, y=None):
        return 0.5


class FakeCatBoostRegressor:
    def __init__(self, evals=None, best_iteration=None):
        self._evals = evals or {}
        self._best = best_iteration

    def get_params(self, deep=True):
        return {"iterations": 3}

    def fit(self, X, y=None, eval_set=None):
        self.best_score_ = {"learn": {"RMSE": 0.1}}
        return self

    def get_evals_result(self):
        return self._evals

    def get_best_iteration(self):
        return self._best

    def save_model(self, path):
        with open(path, "w") as handle:
            handle.write("cbm")

    def score(self, X, y=None):
        return 0.25


class FakeRun:
    def __init__(self):
        self.param_calls = []
        self.metric_calls = []
        self.artifacts = []

    @property
    def params(self):
        return {k: v for call in self.param_calls for k, v in call.items()}

    def log_params(self, mapping):
        self.param_calls.append(dict(mapping))

    def log_metrics(self, mapping, step=None):
        self.metric_calls.append((dict(mapping), step))

    def log_artifact(self, path):
        self.artifacts.append((os.path.basename(path), os.path.isfile(path)))


def _purge():
    return {
        name: sys.modules.pop(name)
        for name in list(sys.modules)
        if name in _ROOTS or name.startswith(tuple(f"{r}." for r in _ROOTS))
    }


@pytest.fixture(autouse=True)
def clean_framework_state():
    classes = (FakeLGBMRegressor, FakeCatBoostRegressor)
    originals = [(cls, cls.__dict__["fit"]) for cls in classes]
    saved = _purge()
    yield
    autolog_disable()
    for cls, original in originals:
        cls.fit = original
    _purge()
    sys.modules.update(saved)


@pytest.fixture
def open_run():
    fake = FakeRun()
    run_module._OPEN_RUNS.append(fake)
    yield fake
    run_module._OPEN_RUNS.remove(fake)


def _install(name, **classes):
    module = types.ModuleType(name)
    for attr, cls in classes.items():
        setattr(module, attr, cls)
    sys.modules[name] = module


def _lightgbm():
    _install("lightgbm", LGBMRegressor=FakeLGBMRegressor)


def _catboost():
    _install("catboost", CatBoostRegressor=FakeCatBoostRegressor)


def _series(run, key):
    return [(m[key], step) for m, step in run.metric_calls if key in m]


def test_a_lightgbm_fit_records_its_hyperparameters_under_the_lightgbm_label(open_run):
    _lightgbm()
    autolog()

    FakeLGBMRegressor().fit([[0.0]], [0.0])

    assert open_run.params["lightgbm_n_estimators"] == 3
    assert open_run.params["lightgbm_learning_rate"] == 0.1
    assert open_run.params["lightgbm_estimator"] == "FakeLGBMRegressor"


def test_lightgbm_eval_results_arrive_as_one_series_per_dataset_and_metric(open_run):
    _lightgbm()
    autolog()

    FakeLGBMRegressor(evals={"valid_0": {"l2": [3.0, 2.0, 1.0]}}).fit([[0.0]], [0.0])

    assert _series(open_run, "lightgbm_valid_0_l2") == [(3.0, 0), (2.0, 1), (1.0, 2)]


def test_a_dict_best_score_is_never_logged_as_best_cv_score(open_run):
    _lightgbm()
    autolog()

    FakeLGBMRegressor().fit([[0.0]], [0.0])

    logged = {k for m, _step in open_run.metric_calls for k in m}
    assert "lightgbm_best_cv_score" not in logged
    assert "lightgbm_score" in logged


def test_a_lightgbm_fit_without_an_eval_set_logs_no_series(open_run):
    _lightgbm()
    autolog()

    FakeLGBMRegressor().fit([[0.0]], [0.0])

    assert [step for _m, step in open_run.metric_calls if step is not None] == []


def test_lightgbm_best_iteration_is_recorded_only_when_early_stopping_set_one(open_run):
    _lightgbm()
    autolog()

    FakeLGBMRegressor().fit([[0.0]], [0.0])
    assert "lightgbm_best_iteration" not in open_run.params
    FakeLGBMRegressor(best_iteration=7).fit([[0.0]], [0.0])
    assert open_run.params["lightgbm_best_iteration"] == 7


def test_a_catboost_fit_records_get_evals_result_per_iteration(open_run):
    _catboost()
    autolog()
    evals = {"learn": {"RMSE": [0.3, 0.2]}, "validation": {"RMSE": [0.4, 0.35]}}

    FakeCatBoostRegressor(evals=evals, best_iteration=1).fit([[0.0]], [0.0])

    assert open_run.params["catboost_iterations"] == 3
    assert open_run.params["catboost_best_iteration"] == 1
    assert _series(open_run, "catboost_learn_RMSE") == [(0.3, 0), (0.2, 1)]
    assert _series(open_run, "catboost_validation_RMSE") == [(0.4, 0), (0.35, 1)]


def test_catboost_without_a_best_iteration_records_none(open_run):
    _catboost()
    autolog()

    FakeCatBoostRegressor().fit([[0.0]], [0.0])

    assert "catboost_best_iteration" not in open_run.params


def test_catboost_log_models_saves_through_save_model(open_run):
    _catboost()
    autolog(log_models=True)

    FakeCatBoostRegressor().fit([[0.0]], [0.0])

    assert open_run.artifacts == [("catboost_FakeCatBoostRegressor.cbm", True)]


def test_autolog_imports_neither_lightgbm_nor_catboost():
    autolog()

    assert not set(_ROOTS) & set(sys.modules)


def test_a_failing_eval_result_reader_does_not_break_fit(open_run):
    _catboost()
    autolog()
    model = FakeCatBoostRegressor()
    model.get_evals_result = lambda: 1 / 0

    assert model.fit([[0.0]], [0.0]) is model
    assert open_run.params["catboost_iterations"] == 3
