"""The adapter contract autolog's framework modules share.

:data:`_Adapter` names the five questions the shared recording path asks a
framework (which attributes to wrap, which object is trained, where its
hyperparameters and metrics live, how to save it); :func:`_adapter` fills in the
scikit-learn-shaped answers, which is why those defaults live here too.
"""
import collections
import importlib
import logging
import pickle
import re

from version_stamp.core.experiment_values import _unwrap_scalar

# One logger for every autolog module, so a caller silencing (or capturing)
# ``version_stamp.exp.autolog`` sees all of it.
_LOGGER = logging.getLogger("version_stamp.exp.autolog")

# Read by every wrapper at call time, so a second ``autolog()`` reconfigures the
# wrappers the first one installed instead of being ignored.
_CONFIG = {"log_models": False, "training_score": "auto"}

# ``training_score="auto"`` re-scores the training set only up to this many rows:
# the re-predict costs as much as a fit for neighbour models, and a training-set
# score is a weak signal anyway.
TRAINING_SCORE_MAX_ROWS = 10_000

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


def _guarded(func, *args):
    try:
        func(*args)
    except Exception:
        _LOGGER.debug("vmn autolog failed in %s", func.__name__, exc_info=True)


def _import(name):
    try:
        return importlib.import_module(name)
    except Exception:
        _LOGGER.debug("vmn autolog skipping %r: not importable", name)
        return None


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


# ---------------------------------------------------------------------------
# Defaults: the scikit-learn shape
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Discovery helper
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
