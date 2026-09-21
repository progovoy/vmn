"""Autologging against the real deep-learning frameworks.

``tests/test_exp_autolog.py`` pins the patching machinery down against a fake,
and ``tests/test_exp_autolog_real.py`` does it against scikit-learn and xgboost.
Both of those frameworks have the one shape the original machinery assumed: a
``fit(self, X, y)`` whose ``self`` answers ``get_params()`` and ``score()``.

Keras and Lightning do not. ``keras.Model.fit`` returns the metrics in a
``History`` object rather than leaving them on the model, and
``Trainer.fit(model, ...)`` takes the thing being trained as an *argument* — its
``self`` is the trainer. These tests are what forces the adapter to say where
params, metrics and the saved model come from, instead of assuming.

Everything here is CPU-only, one or two epochs over eight synthetic rows, and
downloads nothing.
"""
import warnings

import pytest

from version_stamp.core.experiment_log import metric_series
from version_stamp.exp import autolog, autolog_disable, start_run
from version_stamp.exp import run as run_module
from version_stamp.exp.autolog import _PATCH_MARKER, SUPPORTED_FRAMEWORKS
from version_stamp.exp.reader import get_run

from helpers import _bootstrap, _storage


@pytest.fixture(autouse=True)
def restore_frameworks():
    """``autolog`` patches the installed libraries globally; undo it every time."""
    yield
    autolog_disable()
    assert run_module._OPEN_RUNS == []


@pytest.fixture(autouse=True)
def quiet_framework_warnings():
    """Eight-row batches make both frameworks grumble; not under test."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _run(app_layout, train, log_models=False, frameworks=None):
    """``autolog()``, run *train* inside one real run, return the run's row."""
    autolog(frameworks=frameworks, log_models=log_models)
    with start_run(app_layout.app_name) as run:
        verstr = run.id
        train()
    return get_run(app_layout.app_name, verstr, storage=_storage(app_layout))


def _fit_owner(cls, attr="fit"):
    for klass in cls.__mro__:
        if attr in vars(klass):
            return klass
    return None


# --- keras -----------------------------------------------------------------


def _keras():
    return pytest.importorskip("keras")


def _keras_model(keras, loss="mse"):
    model = keras.Sequential(
        [
            keras.layers.Input(shape=(2,)),
            keras.layers.Dense(2, activation="relu"),
            keras.layers.Dense(1),
        ]
    )
    model.compile(
        optimizer=keras.optimizers.SGD(learning_rate=0.05),
        loss=loss,
        metrics=["mae"],
    )
    return model


def _keras_data(rows=8):
    numpy = pytest.importorskip("numpy")
    x = numpy.linspace(0.0, 1.0, rows * 2).reshape(rows, 2).astype("float32")
    y = x.sum(axis=1, keepdims=True)
    return x, y


def _fit_keras(model, epochs=2):
    x, y = _keras_data()
    return model.fit(x, y, epochs=epochs, batch_size=4, verbose=0, shuffle=False)


def test_keras_is_registered_as_a_supported_framework():
    assert "keras" in SUPPORTED_FRAMEWORKS


def test_keras_records_the_compiled_optimizer_and_loss(app_layout):
    """There is no ``get_params()`` — the params come off the compiled model."""
    keras = _keras()

    _bootstrap(app_layout)
    model = _keras_model(keras)
    row = _run(app_layout, lambda: _fit_keras(model), frameworks=["keras"])

    params = row["params"]
    assert params["keras_estimator"] == "Sequential"
    assert params["keras_optimizer"] == "SGD"
    assert params["keras_learning_rate"] == pytest.approx(0.05, rel=1e-4)
    assert params["keras_loss_fn"] == "mse"
    assert params["keras_parameter_count"] == model.count_params()


def test_keras_records_the_final_epoch_metrics_from_the_history(app_layout):
    """Keras puts the metrics on ``fit``'s return value, not on the model."""
    keras = _keras()

    _bootstrap(app_layout)
    model = _keras_model(keras)
    history = {}
    row = _run(
        app_layout,
        lambda: history.update(_fit_keras(model).history),
        frameworks=["keras"],
    )

    assert row["metrics"]["keras_loss"] == pytest.approx(history["loss"][-1], rel=1e-5)
    assert row["metrics"]["keras_mae"] == pytest.approx(history["mae"][-1], rel=1e-5)


def test_keras_records_one_point_per_epoch_as_a_step_series(app_layout):
    keras = _keras()

    _bootstrap(app_layout)
    model = _keras_model(keras)
    row = _run(app_layout, lambda: _fit_keras(model, epochs=2), frameworks=["keras"])

    series = metric_series(row["log"])["keras_loss"]
    assert [point["step"] for point in series] == [0, 1]
    assert row["series"]["keras_mae"][0]["step"] == 0


def test_keras_log_models_attaches_the_native_keras_file(app_layout):
    """A Keras model is saved in its own format; pickling it is not the way."""
    keras = _keras()

    _bootstrap(app_layout)
    model = _keras_model(keras)
    row = _run(
        app_layout, lambda: _fit_keras(model), log_models=True, frameworks=["keras"]
    )

    assert len(row["artifacts"]) == 1
    assert row["artifacts"][0]["name"] == "keras_Sequential.keras"
    assert row["artifacts"][0]["size"] > 0


def test_keras_log_models_false_attaches_nothing(app_layout):
    keras = _keras()

    _bootstrap(app_layout)
    model = _keras_model(keras)
    row = _run(
        app_layout, lambda: _fit_keras(model), log_models=False, frameworks=["keras"]
    )

    assert row["artifacts"] == []


def test_autolog_disable_restores_keras_fit():
    keras = _keras()

    owner = _fit_owner(keras.Model)
    original = owner.__dict__["fit"]
    autolog(frameworks=["keras"])
    assert owner.__dict__["fit"] is not original

    autolog_disable()

    assert owner.__dict__["fit"] is original


def test_the_tensorflow_import_name_does_not_double_patch_keras():
    """``tensorflow.keras.Model`` *is* ``keras.Model``; one wrapper, not two."""
    keras = _keras()
    pytest.importorskip("tensorflow")

    owner = _fit_owner(keras.Model)
    original = owner.__dict__["fit"]
    autolog(frameworks=["tensorflow", "keras"])

    patched = owner.__dict__["fit"]
    assert getattr(patched, _PATCH_MARKER) is original


def test_keras_fit_outside_a_run_records_nothing(app_layout):
    keras = _keras()

    _bootstrap(app_layout)
    autolog(frameworks=["keras"], log_models=True)
    model = _keras_model(keras)

    history = _fit_keras(model)  # no run open: plain pass-through

    assert history.history["loss"]  # the real fit still happened

    with start_run(app_layout.app_name) as run:
        verstr = run.id
    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert not [key for key in row["params"] if key.startswith("keras_")]


def test_a_real_keras_fit_failure_propagates_unchanged(app_layout):
    """A wrong input width must raise keras's own error, not ours."""
    keras = _keras()
    numpy = pytest.importorskip("numpy")

    _bootstrap(app_layout)
    autolog(frameworks=["keras"], log_models=True)
    model = _keras_model(keras)

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        with pytest.raises(ValueError):
            model.fit(
                numpy.zeros((8, 5), dtype="float32"),
                numpy.zeros((8, 1), dtype="float32"),
                epochs=1,
                verbose=0,
            )

    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert row["params"]["keras_estimator"] == "Sequential"  # captured before training
    assert "keras_loss" not in row["metrics"]
    assert row["artifacts"] == []


def test_patching_sklearn_and_keras_together_keeps_them_apart(app_layout):
    keras = _keras()
    pytest.importorskip("sklearn")
    from sklearn.linear_model import LinearRegression

    _bootstrap(app_layout)
    x, y = _keras_data()
    model = _keras_model(keras)

    def train():
        LinearRegression().fit(x, y)
        _fit_keras(model, epochs=1)

    row = _run(app_layout, train, frameworks=["sklearn", "keras"])

    assert row["params"]["sklearn_estimator"] == "LinearRegression"
    assert row["params"]["keras_estimator"] == "Sequential"
    assert "sklearn_score" in row["metrics"]
    assert "keras_loss" in row["metrics"]


# --- lightning -------------------------------------------------------------


def _lightning():
    return pytest.importorskip("lightning")


def _lit_module(torch, lightning, hidden=2, lr=0.05):
    class LitMLP(lightning.LightningModule):
        def __init__(self, hidden=hidden, lr=lr):
            super().__init__()
            self.save_hyperparameters()
            self.net = torch.nn.Sequential(
                torch.nn.Linear(2, hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, 1)
            )

        def training_step(self, batch, _index):
            inputs, targets = batch
            loss = torch.nn.functional.mse_loss(self.net(inputs), targets)
            self.log("train_loss", loss)
            return loss

        def configure_optimizers(self):
            return torch.optim.SGD(self.parameters(), lr=self.hparams.lr)

    return LitMLP()


def _lit_loader(torch, width=2):
    from torch.utils.data import DataLoader, TensorDataset

    inputs = torch.linspace(0.0, 1.0, 8 * width).reshape(8, width)
    targets = inputs.sum(dim=1, keepdim=True)
    return DataLoader(TensorDataset(inputs, targets), batch_size=4)


def _lit_trainer(lightning):
    return lightning.Trainer(
        max_epochs=1,
        accelerator="cpu",
        devices=1,
        logger=False,
        enable_checkpointing=False,
        enable_progress_bar=False,
        enable_model_summary=False,
    )


def test_lightning_import_names_are_both_registered():
    assert "lightning" in SUPPORTED_FRAMEWORKS
    assert "pytorch_lightning" in SUPPORTED_FRAMEWORKS


def test_lightning_records_the_module_hyperparameters(app_layout):
    """``Trainer.fit(model)`` — the params belong to the argument, not ``self``."""
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    module = _lit_module(torch, lightning, hidden=3, lr=0.02)
    trainer = _lit_trainer(lightning)
    row = _run(
        app_layout,
        lambda: trainer.fit(module, _lit_loader(torch)),
        frameworks=["lightning"],
    )

    params = row["params"]
    assert params["lightning_estimator"] == "LitMLP"
    assert params["lightning_hidden"] == 3
    assert params["lightning_lr"] == pytest.approx(0.02)
    assert params["lightning_max_epochs"] == 1


def test_lightning_records_the_final_callback_metrics(app_layout):
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    module = _lit_module(torch, lightning)
    trainer = _lit_trainer(lightning)
    row = _run(
        app_layout,
        lambda: trainer.fit(module, _lit_loader(torch)),
        frameworks=["lightning"],
    )

    logged = row["metrics"]["lightning_train_loss"]
    assert isinstance(logged, float)
    assert logged == pytest.approx(float(trainer.callback_metrics["train_loss"]))


def test_lightning_log_models_attaches_a_checkpoint(app_layout):
    """Lightning's own checkpoint, not a pickle of a module holding tensors."""
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    module = _lit_module(torch, lightning)
    trainer = _lit_trainer(lightning)
    row = _run(
        app_layout,
        lambda: trainer.fit(module, _lit_loader(torch)),
        log_models=True,
        frameworks=["lightning"],
    )

    assert len(row["artifacts"]) == 1
    assert row["artifacts"][0]["name"] == "lightning_LitMLP.ckpt"
    assert row["artifacts"][0]["size"] > 0


def test_lightning_log_models_false_attaches_nothing(app_layout):
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    module = _lit_module(torch, lightning)
    trainer = _lit_trainer(lightning)
    row = _run(
        app_layout,
        lambda: trainer.fit(module, _lit_loader(torch)),
        frameworks=["lightning"],
    )

    assert row["artifacts"] == []


def test_autolog_disable_restores_lightning_fit():
    lightning = _lightning()

    owner = _fit_owner(lightning.Trainer)
    original = owner.__dict__["fit"]
    autolog(frameworks=["lightning"])
    assert owner.__dict__["fit"] is not original

    autolog_disable()

    assert owner.__dict__["fit"] is original


def test_pytorch_lightning_is_patched_under_the_lightning_prefix(app_layout):
    """``pytorch_lightning.Trainer`` is a different class object from
    ``lightning.pytorch.Trainer``, so it needs its own patch — but the keys it
    records must not depend on which import name the user reached for."""
    pl = pytest.importorskip("pytorch_lightning")
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    assert pl.Trainer is not lightning.pytorch.Trainer

    _bootstrap(app_layout)
    module = _lit_module(torch, pl)
    trainer = pl.Trainer(
        max_epochs=1,
        accelerator="cpu",
        devices=1,
        logger=False,
        enable_checkpointing=False,
        enable_progress_bar=False,
        enable_model_summary=False,
    )
    row = _run(
        app_layout,
        lambda: trainer.fit(module, _lit_loader(torch)),
        frameworks=["pytorch_lightning"],
    )

    assert row["params"]["lightning_estimator"] == "LitMLP"
    assert "lightning_train_loss" in row["metrics"]


def test_lightning_fit_outside_a_run_records_nothing(app_layout):
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    autolog(frameworks=["lightning"], log_models=True)
    module = _lit_module(torch, lightning)
    trainer = _lit_trainer(lightning)

    trainer.fit(module, _lit_loader(torch))  # no run open: plain pass-through

    assert "train_loss" in trainer.callback_metrics  # the real fit still happened

    with start_run(app_layout.app_name) as run:
        verstr = run.id
    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert not [key for key in row["params"] if key.startswith("lightning_")]


def test_a_real_lightning_fit_failure_propagates_unchanged(app_layout):
    """A mismatched feature width must raise torch's own error, not ours."""
    lightning = _lightning()
    torch = pytest.importorskip("torch")

    _bootstrap(app_layout)
    autolog(frameworks=["lightning"], log_models=True)
    module = _lit_module(torch, lightning)
    trainer = _lit_trainer(lightning)

    with start_run(app_layout.app_name) as run:
        verstr = run.id
        with pytest.raises(RuntimeError):
            trainer.fit(module, _lit_loader(torch, width=5))

    row = get_run(app_layout.app_name, verstr, storage=_storage(app_layout))
    assert row["params"]["lightning_estimator"] == "LitMLP"
    assert "lightning_train_loss" not in row["metrics"]
    assert row["artifacts"] == []


# --- plain torch -----------------------------------------------------------


def test_plain_torch_is_deliberately_not_a_framework():
    """Raw PyTorch has no training entry point to wrap.

    The user writes the loop, so there is no ``fit`` — and the candidates
    (``Module.__call__``, ``Optimizer.step``) fire per batch or per forward pass
    and would flood the log while still not knowing an epoch from a step. Raw
    torch users call ``run.log_metric`` in their own loop; see docs/sdk.md.
    """
    pytest.importorskip("torch")

    assert "torch" not in SUPPORTED_FRAMEWORKS
