"""Framework autologging: ``from version_stamp.exp import autolog``.

No ML framework is installed in the test venv (and none should be — torch alone
is gigabytes), so these tests inject a minimal fake ``sklearn`` package into
``sys.modules`` and run the *real* patching logic against it. That exercises
what actually breaks in autologging — target discovery, param capture,
idempotency, restoration, error containment — without the dependency.
"""
import logging
import os
import sys
import types

import pytest

from version_stamp.exp import autolog, autolog_disable
from version_stamp.exp import run as run_module
from helpers import _bootstrap, _storage

_AUTOLOG_LOGGER = "version_stamp.exp.autolog"


# --- the fake framework ----------------------------------------------------
# Module-level classes on purpose: they are importable by name, so ``pickle``
# can dump an instance the way it would dump a real fitted estimator.


class FakeBaseEstimator:
    """Stands in for ``sklearn.base.BaseEstimator``."""

    _params = {}

    def get_params(self, deep=True):
        return dict(self._params)

    def fit(self, X, y=None):
        self.fitted = X
        return self

    def score(self, X, y=None):
        return 0.5


class FakeSVC(FakeBaseEstimator):
    def __init__(self):
        self._params = {"kernel": "rbf", "C": 2.5, "verbose": False, "cache": None}

    def fit(self, X, y=None):
        self.fitted = X
        return "FITTED"

    def score(self, X, y=None):
        return 0.75


class FakeBoom(FakeBaseEstimator):
    def __init__(self):
        self._params = {"kernel": "linear"}

    def fit(self, X, y=None):
        raise RuntimeError("training blew up")


_FAKE_MODULES = ("sklearn", "sklearn.base", "sklearn.utils")


def _install_fake_sklearn(estimators=(FakeSVC, FakeBoom), with_all_estimators=True):
    sklearn = types.ModuleType("sklearn")
    base = types.ModuleType("sklearn.base")
    base.BaseEstimator = FakeBaseEstimator
    sklearn.base = base
    sys.modules["sklearn"] = sklearn
    sys.modules["sklearn.base"] = base

    if with_all_estimators:
        utils = types.ModuleType("sklearn.utils")
        utils.all_estimators = lambda: [(c.__name__, c) for c in estimators]
        sklearn.utils = utils
        sys.modules["sklearn.utils"] = utils

    return sklearn


def _shadowed_modules():
    """Every real module the fake would shadow, plus anything that lazily
    imports it.

    A counterfeit ``sklearn`` in ``sys.modules`` poisons more than itself:
    xgboost imports sklearn on demand and caches the failure, so a later test
    against the real libraries dies with "sklearn needs to be installed". Purge
    the whole subtree of both and let them import fresh.
    """
    return [
        name
        for name in list(sys.modules)
        if name == "sklearn"
        or name.startswith("sklearn.")
        or name == "xgboost"
        or name.startswith("xgboost.")
    ]


@pytest.fixture(autouse=True)
def clean_framework_state():
    """No fake module and no patch may leak into the next test."""
    originals = [
        (cls, cls.__dict__["fit"]) for cls in (FakeBaseEstimator, FakeSVC, FakeBoom)
    ]
    saved = {name: sys.modules[name] for name in _shadowed_modules()}
    for name in saved:
        sys.modules.pop(name, None)

    yield

    autolog_disable()
    for cls, original in originals:
        setattr(cls, "fit", original)
    for name in _shadowed_modules():
        sys.modules.pop(name, None)
    sys.modules.update(saved)


class FakeRun:
    """Records what autolog hands a run, in the order it hands it over."""

    def __init__(self):
        self.param_calls = []
        self.metric_calls = []
        self.artifacts = []

    @property
    def params(self):
        merged = {}
        for call in self.param_calls:
            merged.update(call)
        return merged

    @property
    def metrics(self):
        merged = {}
        for call in self.metric_calls:
            merged.update(call)
        return merged

    def log_params(self, mapping):
        self.param_calls.append(dict(mapping))

    def log_metrics(self, mapping, step=None):
        self.metric_calls.append(dict(mapping))

    def log_metric(self, key, value, step=None):
        self.log_metrics({key: value})

    def log_artifact(self, path):
        self.artifacts.append((path, os.path.isfile(path)))


@pytest.fixture
def open_run():
    """Push a fake run onto the SDK's open-run stack, as ``start_run`` would."""
    fake = FakeRun()
    run_module._OPEN_RUNS.append(fake)
    yield fake
    run_module._OPEN_RUNS.remove(fake)


# --- absent framework ------------------------------------------------------


def test_autolog_is_a_silent_noop_when_no_framework_is_importable(caplog):
    assert "sklearn" not in sys.modules
    with caplog.at_level(logging.WARNING):
        autolog()
    assert caplog.records == []


def test_autolog_disable_without_any_patch_is_safe():
    autolog_disable()
    autolog_disable()


def test_unknown_framework_name_is_ignored():
    _install_fake_sklearn()
    original = FakeSVC.__dict__["fit"]
    autolog(frameworks=["torch"])
    assert FakeSVC.__dict__["fit"] is original


# --- patch discovery -------------------------------------------------------


def test_autolog_patches_every_concrete_estimator_fit():
    _install_fake_sklearn()
    originals = {cls: cls.__dict__["fit"] for cls in (FakeSVC, FakeBoom)}

    autolog()

    for cls, original in originals.items():
        assert cls.__dict__["fit"] is not original


def test_discovery_falls_back_to_base_estimator():
    _install_fake_sklearn(with_all_estimators=False)
    original = FakeBaseEstimator.__dict__["fit"]

    autolog()

    assert FakeBaseEstimator.__dict__["fit"] is not original


# --- what gets logged ------------------------------------------------------


def test_hyperparameters_are_captured_verbatim(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)

    FakeSVC().fit([[1.0]], [1])

    params = open_run.params
    assert params["sklearn_kernel"] == "rbf"  # a string survives as a string
    assert params["sklearn_C"] == 2.5
    assert params["sklearn_verbose"] is False
    assert params["sklearn_cache"] is None
    assert params["sklearn_estimator"] == "FakeSVC"


def test_training_score_is_logged_as_a_metric(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)

    FakeSVC().fit([[1.0]], [1])

    assert open_run.metrics == {"sklearn_score": 0.75}


def test_log_models_pickles_the_fitted_estimator(open_run):
    _install_fake_sklearn()
    autolog(log_models=True)

    FakeSVC().fit([[1.0]], [1])

    assert len(open_run.artifacts) == 1
    path, existed = open_run.artifacts[0]
    assert existed
    assert path.endswith(".pkl")


def test_log_models_false_logs_no_artifact(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)

    FakeSVC().fit([[1.0]], [1])

    assert open_run.artifacts == []


# --- the user's fit must be untouched --------------------------------------


def test_fit_return_value_passes_through(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)

    estimator = FakeSVC()
    assert estimator.fit([[1.0]], [1]) == "FITTED"
    assert estimator.fitted == [[1.0]]


def test_fit_exception_propagates_unchanged(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)

    with pytest.raises(RuntimeError, match="training blew up"):
        FakeBoom().fit([[1.0]], [1])

    # params were captured before training, the score never was
    assert open_run.params["sklearn_kernel"] == "linear"
    assert open_run.metrics == {}


def test_a_raising_run_never_breaks_fit(open_run, caplog):
    _install_fake_sklearn()
    autolog(log_models=True)

    def explode(*args, **kwargs):
        raise IOError("storage is on fire")

    open_run.log_params = explode
    open_run.log_metrics = explode
    open_run.log_artifact = explode

    with caplog.at_level(logging.DEBUG, logger=_AUTOLOG_LOGGER):
        assert FakeSVC().fit([[1.0]], [1]) == "FITTED"


def test_fit_signature_metadata_is_preserved():
    _install_fake_sklearn()
    autolog()
    assert FakeSVC.fit.__name__ == "fit"


# --- idempotency and restoration ------------------------------------------


def test_double_autolog_does_not_double_wrap(open_run):
    _install_fake_sklearn()
    autolog(log_models=False)
    patched = FakeSVC.__dict__["fit"]

    autolog(log_models=False)

    assert FakeSVC.__dict__["fit"] is patched
    FakeSVC().fit([[1.0]], [1])
    assert len(open_run.param_calls) == 1
    assert len(open_run.metric_calls) == 1


def test_autolog_disable_restores_the_exact_original(open_run):
    _install_fake_sklearn()
    originals = {cls: cls.__dict__["fit"] for cls in (FakeSVC, FakeBoom)}
    autolog(log_models=False)

    autolog_disable()

    for cls, original in originals.items():
        assert cls.__dict__["fit"] is original
    FakeSVC().fit([[1.0]], [1])
    assert open_run.param_calls == []


def test_disable_after_double_autolog_still_restores(open_run):
    _install_fake_sklearn()
    original = FakeSVC.__dict__["fit"]
    autolog(log_models=False)
    autolog(log_models=False)

    autolog_disable()
    autolog_disable()

    assert FakeSVC.__dict__["fit"] is original


# --- no open run -----------------------------------------------------------


def test_nothing_is_logged_when_no_run_is_open(caplog):
    _install_fake_sklearn()
    autolog(log_models=True)
    assert run_module._OPEN_RUNS == []

    with caplog.at_level(logging.DEBUG, logger=_AUTOLOG_LOGGER):
        assert FakeSVC().fit([[1.0]], [1]) == "FITTED"

    assert any("no active vmn run" in record.message for record in caplog.records)


# --- integration with a real run ------------------------------------------


def test_autolog_logs_into_the_open_sdk_run(app_layout):
    _bootstrap(app_layout)
    _install_fake_sklearn()
    autolog(log_models=False)

    from version_stamp.exp import start_run

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        FakeSVC().fit([[1.0]], [1])

    entries = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    params = {}
    for entry in entries:
        if entry["type"] == "params":
            params.update(entry["params"])
    metrics = {}
    for entry in entries:
        if entry["type"] == "metrics":
            metrics.update(entry["values"])

    assert params["sklearn_kernel"] == "rbf"
    assert params["sklearn_C"] == 2.5
    assert metrics["sklearn_score"] == 0.75
