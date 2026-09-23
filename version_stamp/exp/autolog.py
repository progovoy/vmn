"""Framework autologging: record hyperparameters and scores without call sites.

``autolog()`` wraps a framework's training entry point so that every ``fit()``
inside an open ``start_run()`` records the model's hyperparameters, its metrics —
per epoch, where the framework reports them that way — and (optionally) the
trained model, with no changes to the training code.

Four rules shape everything here:

* **Never break training.** Every logging step runs through :func:`_guarded`,
  which swallows the failure into a debug log. The user's call, its return value
  and any exception it raises pass through untouched.
* **Never log behind the user's back.** With no run on the SDK's open-run stack
  the wrapper is a pass-through plus one debug line. Implicitly opening a run
  would snapshot the repository — and stamp a dev version — as a side effect of
  calling ``fit()``, which is not a surprise an SDK gets to spring.
* **Patching is reversible and idempotent.** Each wrapper carries the function
  it replaced under :data:`_PATCH_MARKER`, so a second ``autolog()`` recognizes
  its own work and leaves it alone, and :func:`autolog_disable` puts the exact
  original attribute back.
* **One record per training call.** Meta-estimators train other estimators from
  inside their own ``fit`` — a pipeline fits each step, a forest fits each tree
  — and every one of those is a patched ``fit`` too. Only the outermost call
  records, so the row describes the estimator the user actually trained instead
  of whichever sub-estimator happened to finish last. That holds across
  threads too: a framework's worker threads never record, while each thread
  that opened its own run records into it (see :func:`_recording_target`).

Adding a framework
------------------
Register an :func:`_adapter` in :data:`SUPPORTED_FRAMEWORKS` under the
framework's import name. An adapter answers the five questions the shared
recording path asks — which attributes to wrap, which object is being trained,
where its hyperparameters live, where its metrics live, and how to save it —
because the frameworks disagree on every one of them: scikit-learn hands the
metrics back on the estimator, Keras returns them in a ``History``, and
``Trainer.fit(model, ...)`` trains an *argument* rather than its own ``self``.

``sklearn``, ``xgboost``, ``keras`` (which is also what ``tensorflow.keras``
is) and Lightning under both its import names ship today, each covered by
integration tests against the real library.

Plain ``torch`` is deliberately absent: there is no training entry point to
wrap. The user writes the loop, and the candidate hooks are worse than nothing
— ``Module.__call__`` fires on every forward pass, ``Optimizer.step`` on every
batch, and neither knows an epoch from a step. Raw-torch users call
``run.log_metric`` in their own loop.
"""
import collections
import functools
import importlib
import logging
import os
import pickle
import re
import sys
import tempfile
import threading
import weakref

from version_stamp.exp import import_hooks

_LOGGER = logging.getLogger(__name__)

# Set on every wrapper, holding the function it replaced.
_PATCH_MARKER = "_vmn_autolog_original"

# (owner, attr, original), innermost-last so unwinding restores in reverse.
_PATCHES = []

# Read by every wrapper at call time, so a second ``autolog()`` reconfigures the
# wrappers the first one installed instead of being ignored.
_CONFIG = {"log_models": False, "training_score": "auto"}

# ``training_score="auto"`` re-scores the training set only up to this many rows:
# the re-predict costs as much as a fit for neighbour models, and a training-set
# score is a weak signal anyway.
TRAINING_SCORE_MAX_ROWS = 10_000

# Per-thread "a recording fit is already in progress", so nested training calls
# in the same thread stay silent.
_LOCAL = threading.local()


class _ActiveFits:
    """How many recording fits are in progress in this process, by any thread.

    Frameworks fit sub-estimators in worker threads of their own (joblib's
    threading backend, bagging with ``prefer="threads"``). Those threads have no
    run bound to their context, and while a recording fit is in progress they
    are its workers — never a second training call worth a record.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self._lock = threading.Lock()
        self._count = 0

    def enter(self):
        with self._lock:
            self._count += 1

    def exit(self):
        with self._lock:
            self._count = max(0, self._count - 1)

    def busy(self):
        return self._count > 0


_ACTIVE = _ActiveFits()
if hasattr(os, "register_at_fork"):
    # A forked child inherits the counter mid-fit; it is not fitting anything.
    os.register_at_fork(after_in_child=_ACTIVE.reset)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def autolog(frameworks=None, log_models=False, training_score="auto"):
    """Patch every supported framework. *frameworks* narrows it.

    Frameworks the script already imported are patched immediately; the rest
    are patched the moment they are first imported, so ``autolog()`` itself
    never imports a framework the script does not use. An absent framework is a
    silent no-op, so this is safe to call at import time.

    Args:
        log_models: also save each trained model as an artifact. Off by default:
            it writes, hashes and copies a file per fit on the training thread.
        training_score: record ``<framework>_score``, the estimator's ``score()``
            on its *training* data — ``True``, ``False`` or ``"auto"`` (only when
            the input has at most :data:`TRAINING_SCORE_MAX_ROWS` rows).

    Calling it again with other options reconfigures the installed wrappers.
    """
    _CONFIG.update(log_models=bool(log_models), training_score=training_score)
    names = list(SUPPORTED_FRAMEWORKS) if frameworks is None else list(frameworks)
    for name in names:
        if name not in SUPPORTED_FRAMEWORKS:
            _LOGGER.debug("vmn autolog has no adapter for %r", name)
            continue
        module = sys.modules.get(name)
        if module is not None:
            _patch_framework(name, module)
        else:
            import_hooks.when_imported(name, functools.partial(_patch_framework, name))


def autolog_disable():
    """Restore every patched attribute and drop pending hooks. Always safe."""
    import_hooks.clear()
    while _PATCHES:
        owner, attr, original = _PATCHES.pop()
        try:
            setattr(owner, attr, original)
        except Exception:
            _LOGGER.debug("vmn autolog could not unpatch %s", attr, exc_info=True)


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------


def _import(name):
    try:
        return importlib.import_module(name)
    except Exception:
        _LOGGER.debug("vmn autolog skipping %r: not importable", name)
        return None


def _patch_framework(name, module):
    adapter = SUPPORTED_FRAMEWORKS[name]
    try:
        targets = adapter.discover(module)
    except Exception:
        _LOGGER.debug("vmn autolog could not discover %r", name, exc_info=True)
        return
    for owner, attr in targets:
        _patch(owner, attr, adapter)


def _patch(owner, attr, adapter):
    current = owner.__dict__.get(attr)
    if current is None or getattr(current, _PATCH_MARKER, None) is not None:
        return  # missing, or already ours — never double-wrap

    wrapper = _wrap_fit(current, adapter)
    setattr(wrapper, _PATCH_MARKER, current)  # after functools.wraps copied __dict__
    setattr(owner, attr, wrapper)
    _PATCHES.append((owner, attr, current))


def _wrap_fit(original, adapter):
    @functools.wraps(original)
    def fit(self, *args, **kwargs):
        if getattr(_LOCAL, "recording", False):
            return original(self, *args, **kwargs)  # nested: the outer fit records

        run = _recording_target(type(self).__name__)
        if run is None:
            return original(self, *args, **kwargs)

        call = _Call(self, args, kwargs, None, {})
        _LOCAL.recording = True
        _ACTIVE.enter()
        try:
            _guarded(_log_hyperparameters, run, adapter, call)
            call = _instrumented(adapter, call, run)
            result = original(self, *call.args, **call.kwargs)
            trained = call._replace(result=result)
            _guarded(_log_metric_series, run, adapter, trained)
            _guarded(_log_final_metrics, run, adapter, trained)
            _guarded(_log_fitted_params, run, adapter, trained)
            if _CONFIG["log_models"]:
                _guarded(_log_model, run, adapter, trained)
        finally:
            _ACTIVE.exit()
            _LOCAL.recording = False
        return result

    return fit


def _recording_target(estimator):
    """The run this fit records into, or ``None``.

    The run bound to the calling context wins, so each thread of a thread-pool
    sweep records into the trial it opened. A thread with no run of its own
    records into the process's only open run — unless another recording fit is
    in progress, in which case it is that fit's worker. A forked child sees no
    open run at all: only runs created by this pid count.
    """
    from version_stamp.exp import context

    own = context.context_run()
    if own is not None:
        return own
    if _ACTIVE.busy():
        _LOGGER.debug("vmn autolog: %s.fit is a worker of a recording fit", estimator)
        return None
    run = context.current_run()
    if run is None:
        _LOGGER.debug("vmn autolog: no active vmn run, not recording %s.fit", estimator)
    return run


def _instrumented(adapter, call, run):
    """The call the adapter wants made instead (Keras adds a callback)."""
    try:
        return adapter.instrument(call, run)
    except Exception:
        _LOGGER.debug("vmn autolog could not instrument the fit", exc_info=True)
        return call


def _guarded(func, *args):
    try:
        func(*args)
    except Exception:
        _LOGGER.debug("vmn autolog failed in %s", func.__name__, exc_info=True)


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def _key(label, name):
    """``sklearn_kernel`` — underscores, not dots.

    The key namespaces autologged values away from the user's own, and stays a
    single segment so the query language's two-part ``params.<key>`` /
    ``metrics.<key>`` paths keep resolving it.
    """
    return f"{label}_{name}"


_ADDRESS = re.compile(r" at 0x[0-9A-Fa-f]+")


def _plain(value):
    """Keep scalars verbatim so they stay queryable; describe the rest.

    numpy scalars and 0-d arrays/tensors become the Python number they hold, so
    ``max_depth=np.int64(3)`` queries as ``3``. A repr's memory address is
    dropped, or two identical runs would differ in every object-valued param.
    """
    value = _unwrap_scalar(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return _ADDRESS.sub("", repr(value))


def _unwrap_scalar(value):
    item = getattr(value, "item", None)
    if not callable(item) or tuple(getattr(value, "shape", (None,))) != ():
        return value
    try:
        return item()
    except Exception:
        return value


def _number(value):
    """*value* as a float, or ``None`` when it is not a number.

    Deliberately wider than ``isinstance(value, float)``: framework metrics
    arrive as numpy scalars and zero-dimensional torch tensors, and both convert
    cleanly. ``bool`` is excluded — ``True`` is not a measurement.
    """
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _log_hyperparameters(run, adapter, call):
    params = {}
    for name, value in adapter.params(call).items():
        # A meta-estimator's own ``estimator`` param must not overwrite the
        # recorded class name, which is what queries filter on.
        key = "param_estimator" if name == "estimator" else name
        params[_key(adapter.label, key)] = _plain(value)
    params[_key(adapter.label, "estimator")] = type(adapter.subject(call)).__name__
    run.log_params(params)


def _log_fitted_params(run, adapter, call):
    """Params that only exist once training is done — a search's best params."""
    fitted = adapter.fitted_params(call)
    if fitted:
        run.log_params({_key(adapter.label, k): _plain(v) for k, v in fitted.items()})


def _log_final_metrics(run, adapter, call):
    values = {}
    for name, value in adapter.metrics(call).items():
        number = _number(value)
        if number is not None:
            values[_key(adapter.label, name)] = number
    if values:
        run.log_metrics(values)


def _log_metric_series(run, adapter, call):
    """One ``log_metrics`` per step, so a curve arrives as a curve.

    The last point of each series is also the framework's final value for that
    metric, and the store folds a metric to its latest value — so an adapter with
    a series needs no separate final-metrics extractor.
    """
    series = adapter.series(call)
    steps = max((len(points) for points in series.values()), default=0)
    for step in range(steps):
        values = {}
        for name, points in series.items():
            number = _number(points[step]) if step < len(points) else None
            if number is not None:
                values[_key(adapter.label, name)] = number
        if values:
            run.log_metrics(values, step=step)


def _log_model(run, adapter, call):
    subject = adapter.subject(call)
    name = _artifact_name(run, f"{adapter.label}_{type(subject).__name__}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = adapter.save(call, subject, os.path.join(tmp_dir, name))
        if path:
            run.log_artifact(path)


# run -> Counter of artifact base names. Weak, so a finished run is forgotten.
_ARTIFACT_SEQ = weakref.WeakKeyDictionary()


def _artifact_name(run, base):
    """``base`` for a run's first model of a kind, then ``base_2``, ``base_3``...

    Artifacts are stored by basename, so a second fit in the same run would
    otherwise replace the first file while its log entry kept the old digest.
    """
    try:
        seen = _ARTIFACT_SEQ.setdefault(run, collections.Counter())
    except TypeError:  # not weak-referenceable: no history to collide with
        seen = collections.Counter()
    seen[base] += 1
    return base if seen[base] == 1 else f"{base}_{seen[base]}"


# ---------------------------------------------------------------------------
# The adapter contract
# ---------------------------------------------------------------------------

#: One intercepted training call. ``instance`` is the patched method's ``self``,
#: ``result`` its return value — ``None`` while recording pre-training params.
#: ``state`` is scratch space an adapter's hooks share within one call.
_Call = collections.namedtuple(
    "_Call", "instance args kwargs result state", defaults=(None,)
)

#: What a framework has to tell the shared recording path.
#:
#: ``label`` prefixes every recorded name, and is not the import name: Lightning
#: is reachable as both ``lightning`` and ``pytorch_lightning``, and a query must
#: not have to care which one the training script imported.
#:
#: ``instrument(call, run)`` returns the call to make instead (Keras adds a
#: per-epoch callback); ``fitted_params(call)`` names params that only exist
#: after training.
_Adapter = collections.namedtuple(
    "_Adapter",
    "label discover subject params metrics series save instrument fitted_params",
)


def _adapter(
    label,
    discover,
    params=None,
    metrics=None,
    subject=None,
    series=None,
    save=None,
    instrument=None,
    fitted_params=None,
):
    """An :data:`_Adapter` with the scikit-learn-shaped defaults filled in."""
    return _Adapter(
        label=label,
        discover=discover,
        subject=subject or _fit_self,
        params=params or _get_params,
        metrics=metrics or _score_metric,
        series=series or _no_series,
        save=save or _pickle_model,
        instrument=instrument or _as_called,
        fitted_params=fitted_params or _best_params,
    )


def _fit_self(call):
    """The object ``fit`` was called on — true everywhere but Lightning."""
    return call.instance


def _as_called(call, run):
    return call


def _no_params(call):
    return {}


def _no_series(call):
    return {}


def _no_metrics(call):
    return {}


def _pickle_model(call, subject, base):
    path = base + ".pkl"
    with open(path, "wb") as handle:
        pickle.dump(subject, handle)
    return path


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _fit_owners(classes):
    """``(owner, "fit")`` for each class that *defines* the ``fit`` these inherit.

    Patching ``cls.fit`` only works when ``cls.__dict__`` holds it. Plenty of
    estimators inherit ``fit`` from a shared base instead —
    ``RandomForestClassifier`` gets it from the private ``BaseForest``,
    ``XGBRegressor`` from ``XGBModel`` — and those bases are not themselves
    listed as estimators, so looking only at each class's own ``__dict__``
    silently skips them. Resolving the MRO owner catches them, and deduplicating
    means one wrapper per shared base rather than one per subclass.
    """
    owners = []
    seen = set()
    for cls in classes:
        owner = _fit_owner(cls)
        if owner is not None and owner not in seen:
            seen.add(owner)
            owners.append((owner, "fit"))
    return owners


def _fit_owner(cls):
    if not isinstance(cls, type):
        return None
    for klass in cls.__mro__:
        if "fit" in vars(klass):
            return klass
    return None


def _get_params(call):
    """``estimator.get_params()`` — the scikit-learn API, which xgboost also has."""
    get_params = getattr(call.instance, "get_params", None)
    return get_params() if callable(get_params) else {}


def _score_metric(call):
    """A search's ``best_score_``, plus ``estimator.score(X[, y])`` when wanted.

    ``score`` here is measured on the *training* data, which flatters overfit
    models; a search's cross-validated ``best_score_`` is the honest number, so
    it is recorded whenever the estimator has one.
    """
    metrics = {}
    best = getattr(call.instance, "best_score_", None)
    if best is not None:
        metrics["best_cv_score"] = best
    score = getattr(call.instance, "score", None)
    if callable(score) and call.args and _wants_training_score(call.args[0]):
        metrics["score"] = score(*call.args[:2])
    return metrics


def _wants_training_score(X):
    mode = _CONFIG["training_score"]
    if mode != "auto":
        return bool(mode)
    rows = _n_rows(X)
    return rows is not None and rows <= TRAINING_SCORE_MAX_ROWS


def _n_rows(X):
    shape = getattr(X, "shape", None)
    if shape:
        return shape[0] if isinstance(shape[0], int) else None
    try:
        return len(X)
    except TypeError:
        return None


def _best_params(call):
    """``best_params_`` of a fitted search estimator, as ``best_<name>``."""
    best = getattr(call.instance, "best_params_", None)
    if not isinstance(best, dict):
        return {}
    return {f"best_{name}": value for name, value in best.items()}


def _discover_sklearn(module):
    """Whichever class owns each estimator's ``fit``, or ``BaseEstimator.fit``.

    ``BaseEstimator`` does not define ``fit`` at all, so there is nothing to
    patch centrally — hence the walk over ``sklearn.utils.all_estimators()``.
    The base class is the fallback for installations where that helper is
    unavailable.
    """
    targets = _fit_owners(_sklearn_estimator_classes())
    if targets:
        return targets

    base_module = _import("sklearn.base") or module
    base = getattr(base_module, "BaseEstimator", None)
    if isinstance(base, type) and "fit" in vars(base):
        return [(base, "fit")]
    return []


def _sklearn_estimator_classes():
    utils = _import("sklearn.utils")
    all_estimators = getattr(utils, "all_estimators", None)
    if not callable(all_estimators):
        return []
    return [cls for _name, cls in all_estimators()]


def _discover_xgboost(module):
    """The scikit-learn wrappers only — their ``fit`` is the shape we handle.

    ``XGBClassifier`` and ``XGBRegressor`` subclass ``sklearn.base.BaseEstimator``,
    so ``get_params()`` and ``score()`` behave exactly as the recording path
    already expects. The native ``xgboost.train`` / ``Booster`` API is a
    different shape — a function taking a params dict, with no estimator to ask
    for hyperparameters — and is left alone.
    """
    names = ("XGBClassifier", "XGBRegressor")
    return _fit_owners([getattr(module, name, None) for name in names])


def _discover_keras(module):
    """``keras.Model``'s ``fit``, wherever the backend defines it.

    In Keras 3 ``fit`` lives on a backend-specific trainer mixin
    (``TensorFlowTrainer``, ``TorchTrainer``, ...) rather than on ``Model``, so
    the owner has to be resolved rather than assumed.
    """
    return _fit_owners([getattr(module, "Model", None)])


def _discover_tensorflow(module):
    """``tensorflow.keras.Model`` *is* ``keras.Model`` — the same class object.

    So this discovers the same method, and :func:`_patch` recognizes the wrapper
    it already installed and leaves it alone: naming both import names patches
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
        params["learning_rate"] = _number(getattr(optimizer, "learning_rate", None))
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
                number = _number(value)
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


def _discover_lightning(module):
    """``Trainer.fit``, under either of Lightning's two import names.

    ``lightning.pytorch.Trainer`` and ``pytorch_lightning.Trainer`` are distinct
    class objects from two mirrored packages, so each import name really does
    need its own patch — unlike keras/tensorflow, which share one class.
    """
    trainer = getattr(module, "Trainer", None) or getattr(
        getattr(module, "pytorch", None), "Trainer", None
    )
    return _fit_owners([trainer])


def _lightning_module(call):
    """``Trainer.fit(model, ...)`` trains its first argument, not its ``self``."""
    return call.args[0] if call.args else call.kwargs.get("model")


def _lightning_params(call):
    """The trainer's budget, then the module's ``hparams``, which win on a clash."""
    trainer = call.instance
    params = {
        "max_epochs": getattr(trainer, "max_epochs", None),
        "precision": getattr(trainer, "precision", None),
    }
    hparams = getattr(_lightning_module(call), "hparams", None)
    params.update(dict(hparams or {}))
    return params


def _lightning_metrics(call):
    """``trainer.callback_metrics`` — what the module logged, as it stood at the end."""
    return dict(getattr(call.instance, "callback_metrics", None) or {})


# Trainers already warned about, so a multi-fit script warns once per trainer.
_DDP_WARNED = weakref.WeakSet()


def _save_lightning_checkpoint(call, subject, base):
    """Lightning's own checkpoint, which restores through ``load_from_checkpoint``.

    Skipped under multi-process training: ``save_checkpoint`` ends in a barrier
    every rank must reach, and only the rank that opened a run gets here — so
    calling it would hang that rank until the process-group timeout.
    """
    trainer = call.instance
    world_size = getattr(trainer, "world_size", 1) or 1
    if world_size > 1:
        if trainer not in _DDP_WARNED:
            _DDP_WARNED.add(trainer)
            _LOGGER.warning(
                "vmn autolog: not saving the Lightning model (world_size=%s); "
                "save_checkpoint must run on every rank — log it yourself with "
                "run.log_artifact() after trainer.save_checkpoint()",
                world_size,
            )
        return None
    path = base + ".ckpt"
    trainer.save_checkpoint(path)
    return path


#: Framework import name -> adapter. The extension point.
SUPPORTED_FRAMEWORKS = {
    "sklearn": _adapter("sklearn", _discover_sklearn),
    "xgboost": _adapter("xgboost", _discover_xgboost),
    "keras": _adapter(
        "keras",
        _discover_keras,
        params=_keras_params,
        metrics=_no_metrics,  # the series' last point already is the final value
        series=_keras_series,
        save=_save_keras_model,
        instrument=_keras_instrument,
        fitted_params=_no_params,
    ),
    "lightning": _adapter(
        "lightning",
        _discover_lightning,
        subject=_lightning_module,
        params=_lightning_params,
        metrics=_lightning_metrics,
        save=_save_lightning_checkpoint,
        fitted_params=_no_params,
    ),
}

# The aliases: a second import name for a framework already described above.
# ``tensorflow.keras`` is keras, and Lightning's two packages mirror each other,
# so both reuse the adapter rather than restating it.
SUPPORTED_FRAMEWORKS["tensorflow"] = SUPPORTED_FRAMEWORKS["keras"]._replace(
    discover=_discover_tensorflow
)
SUPPORTED_FRAMEWORKS["pytorch_lightning"] = SUPPORTED_FRAMEWORKS["lightning"]
