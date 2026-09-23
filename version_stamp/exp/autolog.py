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
Register an :func:`_adapter` (``autolog_adapter.py``; one module per
framework, like ``autolog_keras.py``) in :data:`SUPPORTED_FRAMEWORKS` under the
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
import os
import sys
import tempfile
import threading
import weakref

from version_stamp.core.experiment_values import metric_number
from version_stamp.exp import (
    autolog_keras,
    autolog_lightning,
    autolog_sklearn,
    import_hooks,
)
from version_stamp.exp.autolog_adapter import (  # noqa: F401 - the extension API
    _CONFIG,
    _LOGGER,
    TRAINING_SCORE_MAX_ROWS,
    _Adapter,
    _adapter,
    _Call,
    _guarded,
    _key,
    _plain,
)

# Set on every wrapper, holding the function it replaced.
_PATCH_MARKER = "_vmn_autolog_original"

# (owner, attr, original), innermost-last so unwinding restores in reverse.
_PATCHES = []

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


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


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
        number = metric_number(value)
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
            number = metric_number(points[step]) if step < len(points) else None
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


#: Framework import name -> adapter. The extension point.
SUPPORTED_FRAMEWORKS = {
    "sklearn": autolog_sklearn.SKLEARN,
    "xgboost": autolog_sklearn.XGBOOST,
    "keras": autolog_keras.KERAS,
    "lightning": autolog_lightning.LIGHTNING,
    # The aliases: a second import name for a framework already described.
    # ``tensorflow.keras`` is keras, and Lightning's two packages mirror each
    # other, so both reuse the adapter rather than restating it.
    "tensorflow": autolog_keras.TENSORFLOW,
    "pytorch_lightning": autolog_lightning.LIGHTNING,
}
