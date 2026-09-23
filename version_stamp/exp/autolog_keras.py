"""Autolog adapter for Keras (which ``tensorflow.keras`` also is).

Metrics stream per epoch through a callback added to the ``fit`` call; the
model is saved in its native ``.keras`` format.
"""
import importlib

from version_stamp.core.experiment_values import metric_number
from version_stamp.exp.autolog_adapter import (
    _adapter,
    _fit_owners,
    _guarded,
    _key,
    _no_metrics,
    _no_params,
)


def _discover_keras(module):
    """``keras.Model``'s ``fit``, wherever the backend defines it.

    In Keras 3 ``fit`` lives on a backend-specific trainer mixin
    (``TensorFlowTrainer``, ``TorchTrainer``, ...) rather than on ``Model``, so
    the owner has to be resolved rather than assumed.
    """
    return _fit_owners([getattr(module, "Model", None)])


def _discover_tensorflow(module):
    """``tensorflow.keras.Model`` *is* ``keras.Model`` — the same class object.

    So this discovers the same method, and the patcher recognizes the wrapper it
    already installed and leaves it alone: naming both import names patches
    once. The entry exists so ``autolog(frameworks=["tensorflow"])`` is not a
    silent no-op, and it shares keras's label so the recorded keys match.
    """
    return _discover_keras(getattr(module, "keras", module))


def _keras_params(call):
    """Whatever ``compile()`` was told, read back off the model."""
    model = call.instance
    params = {}
    optimizer = getattr(model, "optimizer", None)
    if optimizer is not None:
        params["optimizer"] = type(optimizer).__name__
        params["learning_rate"] = metric_number(
            getattr(optimizer, "learning_rate", None)
        )
    loss = getattr(model, "loss", None)
    if loss is not None:
        params["loss_fn"] = loss if isinstance(loss, str) else type(loss).__name__
    if getattr(model, "built", False):
        params["parameter_count"] = model.count_params()
    return params


# ``fit(x, y, batch_size, epochs, verbose, callbacks, ...)``: the positional slot
# a caller could pass the callbacks in.
_KERAS_CALLBACKS_POSITION = 5


def _keras_instrument(call, run):
    """Add a callback that records each epoch's metrics as the epoch ends.

    Reading ``History`` after ``fit()`` returns loses every epoch of a run that
    crashes, stamps all epochs with the same time, and restarts the steps at 0
    on a resumed ``fit(initial_epoch=...)``. The callback gets the true epoch
    number and runs while training does.
    """
    callback = _keras_epoch_callback(call.instance, run)
    if callback is None:
        return call
    args, kwargs = list(call.args), dict(call.kwargs)
    if len(args) > _KERAS_CALLBACKS_POSITION:
        extended = _with_callback(args[_KERAS_CALLBACKS_POSITION], callback)
        if extended is None:
            return call
        args[_KERAS_CALLBACKS_POSITION] = extended
    else:
        extended = _with_callback(kwargs.get("callbacks"), callback)
        if extended is None:
            return call
        kwargs["callbacks"] = extended
    call.state["streamed"] = True
    return call._replace(args=tuple(args), kwargs=kwargs)


def _with_callback(existing, callback):
    """The user's callbacks plus ours — never mutating theirs; None if unknown."""
    if existing is None:
        return [callback]
    if isinstance(existing, (list, tuple)):
        return list(existing) + [callback]
    return None  # a CallbackList or something custom: leave it alone


def _keras_epoch_callback(model, run):
    base = _keras_callback_base(model)
    if base is None:
        return None

    class _VmnEpochMetrics(base):
        def on_epoch_end(self, epoch, logs=None):
            values = {}
            for name, value in (logs or {}).items():
                number = metric_number(value)
                if number is not None:
                    values[_key("keras", name)] = number
            if values:
                _guarded(run.log_metrics, values, int(epoch))

    return _VmnEpochMetrics()


def _keras_callback_base(model):
    """``Callback`` from the Keras the model comes from (keras 3, tf.keras...)."""
    root = type(model).__module__.split(".")[0]
    for name in (f"{root}.callbacks", "keras.callbacks", "tensorflow.keras.callbacks"):
        try:
            return importlib.import_module(name).Callback
        except Exception:
            continue
    return None


def _keras_series(call):
    """``History.history`` — only when the per-epoch callback could not be added.

    Otherwise the epochs were already recorded as they ended, and replaying the
    history would log each of them twice.
    """
    if (call.state or {}).get("streamed"):
        return {}
    return dict(getattr(call.result, "history", None) or {})


def _save_keras_model(call, subject, base):
    """The native ``.keras`` archive. Pickling a Keras model is not the way."""
    path = base + ".keras"
    subject.save(path)
    return path


KERAS = _adapter(
    "keras",
    _discover_keras,
    params=_keras_params,
    metrics=_no_metrics,  # the series' last point already is the final value
    series=_keras_series,
    save=_save_keras_model,
    instrument=_keras_instrument,
    fitted_params=_no_params,
)
TENSORFLOW = KERAS._replace(discover=_discover_tensorflow)
