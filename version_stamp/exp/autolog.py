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
  of whichever sub-estimator happened to finish last.

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
import tempfile
import threading

_LOGGER = logging.getLogger(__name__)

# Set on every wrapper, holding the function it replaced.
_PATCH_MARKER = "_vmn_autolog_original"

# (owner, attr, original), innermost-last so unwinding restores in reverse.
_PATCHES = []

# Per-thread "a recording fit is already in progress", so nested training calls
# stay silent. Thread-local because frameworks fit sub-estimators in worker
# threads, and two unrelated fits in two threads must each record.
_LOCAL = threading.local()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def autolog(frameworks=None, log_models=True):
    """Patch every supported, importable framework. *frameworks* narrows it.

    An absent framework is a silent no-op, so this is safe to call at import
    time in code that may run without any ML library installed.
    """
    names = list(SUPPORTED_FRAMEWORKS) if frameworks is None else list(frameworks)
    for name in names:
        adapter = SUPPORTED_FRAMEWORKS.get(name)
        if adapter is None:
            _LOGGER.debug("vmn autolog has no adapter for %r", name)
            continue
        module = _import(name)
        if module is None:
            continue
        for owner, attr in adapter.discover(module):
            _patch(owner, attr, adapter, log_models)


def autolog_disable():
    """Restore every patched attribute. Safe when nothing is patched."""
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


def _patch(owner, attr, adapter, log_models):
    current = owner.__dict__.get(attr)
    if current is None or getattr(current, _PATCH_MARKER, None) is not None:
        return  # missing, or already ours — never double-wrap

    wrapper = _wrap_fit(current, adapter, log_models)
    setattr(wrapper, _PATCH_MARKER, current)  # after functools.wraps copied __dict__
    setattr(owner, attr, wrapper)
    _PATCHES.append((owner, attr, current))


def _wrap_fit(original, adapter, log_models):
    @functools.wraps(original)
    def fit(self, *args, **kwargs):
        if getattr(_LOCAL, "recording", False):
            return original(self, *args, **kwargs)  # nested: the outer fit records

        run = _current_run()
        if run is None:
            _LOGGER.debug(
                "vmn autolog: no active vmn run, not recording %s.fit",
                type(self).__name__,
            )
            return original(self, *args, **kwargs)

        call = _Call(self, args, kwargs, None)
        _LOCAL.recording = True
        try:
            _guarded(_log_hyperparameters, run, adapter, call)
            result = original(self, *args, **kwargs)
            trained = call._replace(result=result)
            _guarded(_log_metric_series, run, adapter, trained)
            _guarded(_log_final_metrics, run, adapter, trained)
            if log_models:
                _guarded(_log_model, run, adapter, trained)
        finally:
            _LOCAL.recording = False
        return result

    return fit


def _current_run():
    """The innermost open SDK run, or ``None`` when the user opened none."""
    from version_stamp.exp.run import _OPEN_RUNS

    return _OPEN_RUNS[-1] if _OPEN_RUNS else None


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


def _plain(value):
    """Keep scalars verbatim so they stay queryable; describe the rest."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


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
    params = {_key(adapter.label, "estimator"): type(adapter.subject(call)).__name__}
    for name, value in adapter.params(call).items():
        params[_key(adapter.label, name)] = _plain(value)
    run.log_params(params)


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
    with tempfile.TemporaryDirectory() as tmp_dir:
        base = os.path.join(tmp_dir, f"{adapter.label}_{type(subject).__name__}")
        run.log_artifact(adapter.save(call, subject, base))


# ---------------------------------------------------------------------------
# The adapter contract
# ---------------------------------------------------------------------------

#: One intercepted training call. ``instance`` is the patched method's ``self``,
#: ``result`` its return value — ``None`` while recording pre-training params.
_Call = collections.namedtuple("_Call", "instance args kwargs result")

#: What a framework has to tell the shared recording path.
#:
#: ``label`` prefixes every recorded name, and is not the import name: Lightning
#: is reachable as both ``lightning`` and ``pytorch_lightning``, and a query must
#: not have to care which one the training script imported.
_Adapter = collections.namedtuple(
    "_Adapter", "label discover subject params metrics series save"
)


def _adapter(
    label,
    discover,
    params=None,
    metrics=None,
    subject=None,
    series=None,
    save=None,
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
    )


def _fit_self(call):
    """The object ``fit`` was called on — true everywhere but Lightning."""
    return call.instance


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
    """``estimator.score(X[, y])`` — the framework's own headline metric."""
    score = getattr(call.instance, "score", None)
    if not callable(score) or not call.args:
        return {}
    return {"score": score(*call.args[:2])}


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


def _keras_series(call):
    """``History.history`` — one list per metric, one entry per epoch.

    Keras returns the metrics instead of leaving them on the model, and it
    returns *all* the epochs, so the series needs no callback of its own.
    """
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


def _save_lightning_checkpoint(call, subject, base):
    """Lightning's own checkpoint, which restores through ``load_from_checkpoint``."""
    path = base + ".ckpt"
    call.instance.save_checkpoint(path)
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
    ),
    "lightning": _adapter(
        "lightning",
        _discover_lightning,
        subject=_lightning_module,
        params=_lightning_params,
        metrics=_lightning_metrics,
        save=_save_lightning_checkpoint,
    ),
}

# The aliases: a second import name for a framework already described above.
# ``tensorflow.keras`` is keras, and Lightning's two packages mirror each other,
# so both reuse the adapter rather than restating it.
SUPPORTED_FRAMEWORKS["tensorflow"] = SUPPORTED_FRAMEWORKS["keras"]._replace(
    discover=_discover_tensorflow
)
SUPPORTED_FRAMEWORKS["pytorch_lightning"] = SUPPORTED_FRAMEWORKS["lightning"]
