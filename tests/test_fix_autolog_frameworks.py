"""Per-framework autolog fixes: what gets recorded, and when.

* Keras metrics used to arrive only after ``fit()`` returned — a crash at epoch
  4 of 10 recorded nothing, every epoch carried the same timestamp, and a resumed
  ``fit(initial_epoch=3)`` restarted its steps at 0.
* sklearn search estimators recorded neither ``best_score_`` nor ``best_params_``,
  and the training-set re-score ran on arbitrarily large inputs.
* numpy scalar params were stored as ``'np.int64(3)'`` and object reprs carried
  memory addresses, so identical runs looked different.
* Lightning's ``save_checkpoint`` ends in a DDP barrier: calling it from rank 0
  alone (the only rank with an open run) deadlocks.
"""
import importlib
import logging
import time
import warnings

import pytest
from helpers import _bootstrap, _storage

from version_stamp.core.experiment_log import metric_series
from version_stamp.exp import autolog, autolog_disable, start_run
from version_stamp.exp import run as run_module
from version_stamp.exp.reader import get_run

# The package re-exports the autolog() *function* under the module's name.
autolog_module = importlib.import_module("version_stamp.exp.autolog")


@pytest.fixture(autouse=True)
def restore_frameworks():
    yield
    autolog_disable()
    assert run_module._OPEN_RUNS == []


@pytest.fixture(autouse=True)
def quiet_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _row(app_layout, verstr):
    return get_run(app_layout.app_name, verstr, storage=_storage(app_layout))


# --- keras -------------------------------------------------------------------


def _keras_model(keras):
    model = keras.Sequential(
        [keras.layers.Input(shape=(2,)), keras.layers.Dense(1)]
    )
    model.compile(optimizer=keras.optimizers.SGD(learning_rate=0.01), loss="mse")
    return model


def _keras_data():
    numpy = pytest.importorskip("numpy")
    x = numpy.linspace(0.0, 1.0, 16).reshape(8, 2).astype("float32")
    return x, x.sum(axis=1, keepdims=True)


def test_keras_epochs_before_a_crash_are_kept(app_layout):
    keras = pytest.importorskip("keras")
    _bootstrap(app_layout)
    autolog(frameworks=["keras"])
    model = _keras_model(keras)
    x, y = _keras_data()

    class Boom(keras.callbacks.Callback):
        def on_epoch_end(self, epoch, logs=None):
            if epoch == 2:
                raise RuntimeError("node lost")

    with pytest.raises(RuntimeError, match="node lost"):
        with start_run(app_layout.app_name) as run:
            verstr = run.id
            model.fit(x, y, epochs=10, verbose=0, callbacks=[Boom()])

    series = _row(app_layout, verstr)["series"]["keras_loss"]
    assert [p["step"] for p in series] == [0, 1]


def test_keras_epochs_carry_their_own_timestamps(app_layout):
    keras = pytest.importorskip("keras")
    _bootstrap(app_layout)
    autolog(frameworks=["keras"])
    model = _keras_model(keras)
    x, y = _keras_data()

    class Slow(keras.callbacks.Callback):
        def on_epoch_begin(self, epoch, logs=None):
            time.sleep(0.05)

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        model.fit(x, y, epochs=3, verbose=0, callbacks=[Slow()])

    from version_stamp.core.experiment_status import parse_iso

    series = _row(app_layout, verstr)["series"]["keras_loss"]
    stamps = [parse_iso(p["ts"]) for p in series]
    assert len(stamps) == 3
    # recorded as each epoch ended, not all at once after fit() returned
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
    assert all(gap >= 0.04 for gap in gaps), gaps


def test_keras_resume_uses_the_true_epoch_numbers_and_logs_each_once(app_layout):
    keras = pytest.importorskip("keras")
    _bootstrap(app_layout)
    autolog(frameworks=["keras"])
    model = _keras_model(keras)
    x, y = _keras_data()

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        model.fit(x, y, epochs=3, verbose=0)
        model.fit(x, y, epochs=6, initial_epoch=3, verbose=0)

    row = _row(app_layout, verstr)
    assert [p["step"] for p in row["series"]["keras_loss"]] == [0, 1, 2, 3, 4, 5]
    # the final History is not replayed on top of the streamed epochs
    assert len(metric_series(row["log"])["keras_loss"]) == 6


# --- sklearn -----------------------------------------------------------------


def test_search_estimators_record_best_cv_score_and_best_params(app_layout):
    pytest.importorskip("sklearn")
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV

    X = [[0.0], [1.0], [2.0], [3.0], [10.0], [11.0], [12.0], [13.0]]
    Y = [0, 0, 0, 0, 1, 1, 1, 1]
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        search = GridSearchCV(LogisticRegression(), {"C": [0.01, 1.0]}, cv=2).fit(X, Y)

    row = _row(app_layout, verstr)
    assert row["params"]["sklearn_estimator"] == "GridSearchCV"
    assert row["params"]["sklearn_best_C"] == search.best_params_["C"]
    assert row["metrics"]["sklearn_best_cv_score"] == pytest.approx(search.best_score_)


def test_training_score_is_skipped_for_large_inputs_by_default(app_layout):
    numpy = pytest.importorskip("numpy")
    from sklearn.linear_model import LinearRegression

    x = numpy.arange(20_000, dtype=float).reshape(-1, 1)
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LinearRegression().fit(x, x.ravel())

    assert "sklearn_score" not in _row(app_layout, verstr)["metrics"]


def test_training_score_can_be_forced_on(app_layout):
    numpy = pytest.importorskip("numpy")
    from sklearn.linear_model import LinearRegression

    x = numpy.arange(20_000, dtype=float).reshape(-1, 1)
    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"], training_score=True)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        LinearRegression().fit(x, x.ravel())

    assert _row(app_layout, verstr)["metrics"]["sklearn_score"] == pytest.approx(1.0)


def test_numpy_scalar_params_are_stored_as_plain_numbers(app_layout):
    numpy = pytest.importorskip("numpy")
    from sklearn.tree import DecisionTreeClassifier

    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        DecisionTreeClassifier(max_depth=numpy.int64(3)).fit([[0.0], [1.0]], [0, 1])

    params = _row(app_layout, verstr)["params"]
    assert params["sklearn_max_depth"] == 3
    assert isinstance(params["sklearn_max_depth"], int)


def test_object_param_reprs_carry_no_memory_address(app_layout):
    pytest.importorskip("sklearn")
    from sklearn.preprocessing import FunctionTransformer

    _bootstrap(app_layout)
    autolog(frameworks=["sklearn"])
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        FunctionTransformer(func=lambda v: v).fit([[0.0], [1.0]])

    params = _row(app_layout, verstr)["params"]
    assert "0x" not in str(params["sklearn_func"])
    assert "lambda" in str(params["sklearn_func"])


# --- lightning under DDP -----------------------------------------------------


class _FakeTrainer:
    def __init__(self, world_size):
        self.world_size = world_size
        self.saved = []

    def save_checkpoint(self, path):
        self.saved.append(path)
        with open(path, "wb") as f:
            f.write(b"ckpt")


class _FakeRun:
    def __init__(self):
        self.artifacts = []

    def log_artifact(self, path):
        self.artifacts.append(path)


def _lightning_call(trainer):
    return autolog_module._Call(trainer, (object(),), {}, None)


def test_lightning_never_checkpoints_from_a_single_rank_under_ddp(caplog):
    adapter = autolog_module.SUPPORTED_FRAMEWORKS["lightning"]
    trainer, run = _FakeTrainer(world_size=2), _FakeRun()

    with caplog.at_level(logging.WARNING, logger="version_stamp.exp.autolog"):
        autolog_module._log_model(run, adapter, _lightning_call(trainer))
        autolog_module._log_model(run, adapter, _lightning_call(trainer))

    assert trainer.saved == []
    assert run.artifacts == []
    warned = [r for r in caplog.records if "world_size" in r.getMessage()]
    assert len(warned) == 1


def test_lightning_single_process_still_checkpoints():
    adapter = autolog_module.SUPPORTED_FRAMEWORKS["lightning"]
    trainer, run = _FakeTrainer(world_size=1), _FakeRun()

    autolog_module._log_model(run, adapter, _lightning_call(trainer))

    assert len(trainer.saved) == 1
    assert len(run.artifacts) == 1
