"""Framework autologging: record hyperparameters and scores without call sites.

``autolog()`` wraps a framework's training entry point so that every ``fit()``
inside an open ``start_run()`` records the estimator's hyperparameters, its
training score and (optionally) the fitted model, with no changes to the
training code.

Three rules shape everything here:

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

Adding a framework
------------------
Write a discovery function ``_discover_<name>(module) -> [(owner, attr), ...]``
naming the attributes to wrap — each must be a ``fit(self, X, y=None)``-shaped
method living in ``owner.__dict__`` — and register it in
:data:`SUPPORTED_FRAMEWORKS` under its import name. Nothing else needs to
change: discovery is the only framework-specific part. Only ``sklearn`` ships
today; torch, lightning, xgboost and keras are deliberately unimplemented
rather than written blind against APIs that cannot be imported here.
"""
import functools
import importlib
import logging
import os
import pickle
import tempfile

_LOGGER = logging.getLogger(__name__)

# Set on every wrapper, holding the function it replaced.
_PATCH_MARKER = "_vmn_autolog_original"

# (owner, attr, original), innermost-last so unwinding restores in reverse.
_PATCHES = []


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
        discover = SUPPORTED_FRAMEWORKS.get(name)
        if discover is None:
            _LOGGER.debug("vmn autolog has no adapter for %r", name)
            continue
        module = _import(name)
        if module is None:
            continue
        for owner, attr in discover(module):
            _patch(owner, attr, name, log_models)


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


def _patch(owner, attr, framework, log_models):
    current = owner.__dict__.get(attr)
    if current is None or getattr(current, _PATCH_MARKER, None) is not None:
        return  # missing, or already ours — never double-wrap

    wrapper = _wrap_fit(current, framework, log_models)
    setattr(wrapper, _PATCH_MARKER, current)  # after functools.wraps copied __dict__
    setattr(owner, attr, wrapper)
    _PATCHES.append((owner, attr, current))


def _wrap_fit(original, framework, log_models):
    @functools.wraps(original)
    def fit(self, *args, **kwargs):
        run = _current_run()
        if run is None:
            _LOGGER.debug(
                "vmn autolog: no active vmn run, not recording %s.fit",
                type(self).__name__,
            )
            return original(self, *args, **kwargs)

        _guarded(_log_hyperparameters, run, framework, self)
        result = original(self, *args, **kwargs)
        _guarded(_log_training_score, run, framework, self, args)
        if log_models:
            _guarded(_log_model, run, framework, self)
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


def _key(framework, name):
    """``sklearn_kernel`` — underscores, not dots.

    The key namespaces autologged values away from the user's own, and stays a
    single segment so the query language's two-part ``params.<key>`` /
    ``metrics.<key>`` paths keep resolving it.
    """
    return f"{framework}_{name}"


def _plain(value):
    """Keep scalars verbatim so they stay queryable; describe the rest."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def _log_hyperparameters(run, framework, estimator):
    params = {_key(framework, "estimator"): type(estimator).__name__}
    get_params = getattr(estimator, "get_params", None)
    if callable(get_params):
        for name, value in get_params().items():
            params[_key(framework, name)] = _plain(value)
    run.log_params(params)


def _log_training_score(run, framework, estimator, fit_args):
    """``estimator.score(X[, y])`` — the framework's own headline metric."""
    score = getattr(estimator, "score", None)
    if not callable(score) or not fit_args:
        return
    value = score(*fit_args[:2])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return
    run.log_metrics({_key(framework, "score"): value})


def _log_model(run, framework, estimator):
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, f"{framework}_{type(estimator).__name__}.pkl")
        with open(path, "wb") as handle:
            pickle.dump(estimator, handle)
        run.log_artifact(path)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def _discover_sklearn(module):
    """Each concrete estimator's own ``fit``, or ``BaseEstimator.fit``.

    Estimators override ``fit`` rather than inherit it, so patching
    ``BaseEstimator`` alone would intercept almost nothing — hence the walk over
    ``sklearn.utils.all_estimators()``. The base class is the fallback for
    installations where that helper is unavailable.
    """
    targets = [
        (cls, "fit")
        for cls in _sklearn_estimator_classes()
        if isinstance(cls, type) and "fit" in vars(cls)
    ]
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


#: Framework import name -> discovery function. The extension point.
SUPPORTED_FRAMEWORKS = {"sklearn": _discover_sklearn}
