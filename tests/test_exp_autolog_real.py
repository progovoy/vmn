"""Autologging against the real scikit-learn and xgboost, not a fake.

``tests/test_exp_autolog.py`` unit-tests the patching machinery against a fake
``sklearn`` injected into ``sys.modules``. That is fast and it pins down
idempotency, restoration and error containment, but a fake can only confirm the
assumptions its author already held. These tests run the adapter against the
genuine libraries, where discovery has to cope with estimators that inherit
``fit`` from a private base class and with meta-estimators that call other
estimators' ``fit`` from inside their own.

Every test drives a real SDK ``start_run`` and reads the result back through
``version_stamp.exp.reader``, so what is asserted is what landed on disk.
"""
import warnings

import pytest

sklearn = pytest.importorskip("sklearn")

from version_stamp.core.experiment_query import compile_query  # noqa: E402
from version_stamp.exp import autolog, autolog_disable, start_run  # noqa: E402
from version_stamp.exp import run as run_module  # noqa: E402
from version_stamp.exp.reader import get_run  # noqa: E402

from helpers import _bootstrap, _storage  # noqa: E402

# Four rows, two classes, one feature. Enough for any classifier to fit, small
# enough to cost nothing and to need no download.
X = [[0.0], [1.0], [10.0], [11.0]]
Y = [0, 0, 1, 1]


@pytest.fixture(autouse=True)
def restore_frameworks():
    """``autolog`` patches the installed libraries globally; undo it every time."""
    yield
    autolog_disable()
    assert run_module._OPEN_RUNS == []


@pytest.fixture(autouse=True)
def quiet_convergence_warnings():
    """Tiny datasets make sklearn grumble; the warnings are not under test."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _fit_in_a_run(app_layout, fit, log_models=False, frameworks=None):
    """``autolog()``, run *fit* inside one real run, return the run's row."""
    autolog(frameworks=frameworks, log_models=log_models)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        fit()
    return get_run(app_layout.app_name, verstr, storage=_storage(app_layout))


# --- a plain estimator -----------------------------------------------------


def test_real_estimator_records_its_real_get_params_and_score(app_layout):
    """The headline claim, against the real ``LogisticRegression``."""
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout, lambda: LogisticRegression(C=0.25, max_iter=200).fit(X, Y)
    )

    params = row["params"]
    assert params["sklearn_estimator"] == "LogisticRegression"
    assert params["sklearn_C"] == 0.25
    assert params["sklearn_max_iter"] == 200
    # every key the real get_params() reports is present
    for name in LogisticRegression().get_params():
        assert f"sklearn_{name}" in params

    assert isinstance(row["metrics"]["sklearn_score"], float)


def test_real_non_numeric_hyperparameters_survive_and_are_queryable(app_layout):
    """A string hyperparameter must reach the row verbatim and filter correctly.

    This is the end-to-end claim the docs make: ``params.`` is the verbatim
    view, so ``params.sklearn_solver = "lbfgs"`` is a usable filter.
    """
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout, lambda: LogisticRegression(solver="lbfgs", penalty="l2").fit(X, Y)
    )

    assert row["params"]["sklearn_solver"] == "lbfgs"
    assert row["params"]["sklearn_penalty"] == "l2"

    assert compile_query('params.sklearn_solver = "lbfgs"')(row)
    assert compile_query('params.sklearn_penalty = "l2"')(row)
    assert not compile_query('params.sklearn_solver = "saga"')(row)
    assert compile_query('params.sklearn_estimator ~ "logistic"')(row)


# --- the shapes a fake cannot model ----------------------------------------


def test_a_real_pipeline_logs_the_estimator_fit_was_called_on(app_layout):
    """``Pipeline.fit`` calls each step's ``fit``; only the outer call counts.

    Without a re-entrancy guard the inner steps overwrite
    ``sklearn_estimator`` and ``sklearn_score`` with the last step's values, so
    the row describes a ``LogisticRegression`` the user never trained directly.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    _bootstrap(app_layout)
    pipeline = Pipeline(
        [("scale", StandardScaler()), ("clf", LogisticRegression(C=0.5))]
    )
    row = _fit_in_a_run(app_layout, lambda: pipeline.fit(X, Y))

    assert row["params"]["sklearn_estimator"] == "Pipeline"
    assert "sklearn_score" in row["metrics"]
    # the nested steps did not each log a params entry of their own
    logged = [e for e in row["log"] if e.get("type") == "params"]
    assert len(logged) == 1


def test_a_real_ensemble_that_inherits_fit_is_still_logged(app_layout):
    """``RandomForestClassifier`` has no ``fit`` of its own — it is on ``BaseForest``.

    Patching only the classes ``all_estimators()`` yields that define ``fit``
    themselves misses it entirely, and ``BaseForest`` is private so the walk
    never reaches it. Discovery has to resolve the class that actually owns
    ``fit``.
    """
    from sklearn.ensemble import RandomForestClassifier

    assert "fit" not in vars(RandomForestClassifier), (
        "sklearn changed: RandomForestClassifier now defines its own fit, so "
        "this test no longer covers inherited-fit discovery"
    )

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout, lambda: RandomForestClassifier(n_estimators=3).fit(X, Y)
    )

    assert row["params"]["sklearn_estimator"] == "RandomForestClassifier"
    assert row["params"]["sklearn_n_estimators"] == 3
    assert "sklearn_score" in row["metrics"]


def test_an_ensemble_logs_one_model_not_one_per_sub_estimator(app_layout):
    """A forest fits N trees; ``log_models`` must not pickle each one."""
    from sklearn.ensemble import RandomForestClassifier

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout,
        lambda: RandomForestClassifier(n_estimators=5).fit(X, Y),
        log_models=True,
    )

    assert len(row["artifacts"]) == 1
    assert row["artifacts"][0]["name"] == "sklearn_RandomForestClassifier.pkl"


# --- models ----------------------------------------------------------------


def test_log_models_attaches_a_pickle_of_the_real_estimator(app_layout):
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout, lambda: LogisticRegression().fit(X, Y), log_models=True
    )

    assert len(row["artifacts"]) == 1
    artifact = row["artifacts"][0]
    assert artifact["name"] == "sklearn_LogisticRegression.pkl"
    assert artifact["size"] > 0


def test_log_models_false_attaches_nothing(app_layout):
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout, lambda: LogisticRegression().fit(X, Y), log_models=False
    )

    assert row["artifacts"] == []


# --- opting out and staying out of the way ---------------------------------


def test_autolog_disable_stops_recording_a_real_fit(app_layout):
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    autolog()
    autolog_disable()

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LogisticRegression().fit(X, Y)

    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert not [key for key in row["params"] if key.startswith("sklearn_")]
    assert "sklearn_score" not in row["metrics"]
    assert row["artifacts"] == []


def test_a_real_fit_failure_propagates_unchanged(app_layout):
    """Mismatched shapes must raise sklearn's own error, not ours."""
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    autolog(log_models=True)

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        with pytest.raises(ValueError, match="inconsistent numbers of samples"):
            LogisticRegression().fit(X, [0, 1])

    # params were captured before training; no score, no model
    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert row["params"]["sklearn_estimator"] == "LogisticRegression"
    assert "sklearn_score" not in row["metrics"]
    assert row["artifacts"] == []


def test_a_real_fit_outside_a_run_records_nothing(app_layout):
    from sklearn.linear_model import LogisticRegression

    _bootstrap(app_layout)
    autolog(log_models=True)
    assert run_module._OPEN_RUNS == []

    model = LogisticRegression().fit(X, Y)  # no run open: plain pass-through

    assert model.score(X, Y) >= 0.0  # the real fit still happened

    with start_run(app_layout.app_name) as run:
        verstr = run.id
    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert not [key for key in row["params"] if key.startswith("sklearn_")]


# --- xgboost ---------------------------------------------------------------


def test_xgboost_is_registered_as_a_supported_framework():
    from version_stamp.exp.autolog import SUPPORTED_FRAMEWORKS

    assert "xgboost" in SUPPORTED_FRAMEWORKS


def test_real_xgboost_classifier_is_autologged(app_layout):
    xgboost = pytest.importorskip("xgboost")

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout,
        lambda: xgboost.XGBClassifier(n_estimators=3, max_depth=2).fit(X, Y),
        frameworks=["xgboost"],
    )

    params = row["params"]
    assert params["xgboost_estimator"] == "XGBClassifier"
    assert params["xgboost_n_estimators"] == 3
    assert params["xgboost_max_depth"] == 2
    assert isinstance(row["metrics"]["xgboost_score"], float)
    # the sklearn prefix is not reused for an xgboost estimator
    assert not [key for key in params if key.startswith("sklearn_")]


def test_real_xgboost_regressor_inherits_fit_and_is_still_logged(app_layout):
    """``XGBRegressor`` has no ``fit`` of its own either — it is on ``XGBModel``."""
    xgboost = pytest.importorskip("xgboost")

    assert "fit" not in vars(xgboost.XGBRegressor), (
        "xgboost changed: XGBRegressor now defines its own fit, so this test no "
        "longer covers inherited-fit discovery"
    )

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout,
        lambda: xgboost.XGBRegressor(n_estimators=3).fit(X, Y),
        frameworks=["xgboost"],
    )

    assert row["params"]["xgboost_estimator"] == "XGBRegressor"
    assert "xgboost_score" in row["metrics"]


def test_xgboost_log_models_attaches_a_pickle(app_layout):
    xgboost = pytest.importorskip("xgboost")

    _bootstrap(app_layout)
    row = _fit_in_a_run(
        app_layout,
        lambda: xgboost.XGBClassifier(n_estimators=2).fit(X, Y),
        log_models=True,
        frameworks=["xgboost"],
    )

    assert len(row["artifacts"]) == 1
    assert row["artifacts"][0]["name"] == "xgboost_XGBClassifier.pkl"


def test_autolog_disable_restores_xgboost(app_layout):
    xgboost = pytest.importorskip("xgboost")

    original = xgboost.XGBClassifier.__dict__["fit"]
    autolog(frameworks=["xgboost"])
    assert xgboost.XGBClassifier.__dict__["fit"] is not original

    autolog_disable()

    assert xgboost.XGBClassifier.__dict__["fit"] is original
