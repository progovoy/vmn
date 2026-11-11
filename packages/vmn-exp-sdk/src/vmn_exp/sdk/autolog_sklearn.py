"""Autolog adapters for scikit-learn and xgboost's scikit-learn wrappers.

Both use the adapter defaults (``get_params()``, ``score()``, a pickle), so all
they add is where ``fit`` lives.
"""
import contextlib
import sys
import threading

from vmn_exp.sdk.autolog_adapter import _adapter, _fit_owners, _import


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
    with _refusing_imports(_FOREIGN_ARRAY_SHIMS):
        return [cls for _name, cls in all_estimators()]


#: sklearn's vendored array-API shims for other libraries. They hold no
#: estimators, but ``all_estimators()`` walks them all the same, and each
#: imports its library: ``...torch`` imports torch (on macOS, a second OpenMP
#: runtime that crashes LightGBM and xgboost fits later in the process).
_FOREIGN_ARRAY_SHIMS = tuple(
    f"sklearn.externals.array_api_compat.{lib}" for lib in ("torch", "cupy", "dask")
)


class _RefuseImports:
    """A ``sys.meta_path`` finder refusing the *names* and their submodules.

    Only on the thread that installed it: another thread (a data loader
    importing torch, say) imports as usual. ``pkgutil.walk_packages`` skips a package whose import fails, and a failed
    import is not cached, so a later import of it still works.
    """

    def __init__(self, names):
        self._names = names
        self._subtrees = tuple(f"{name}." for name in names)
        self._thread = threading.get_ident()

    def find_spec(self, name, path=None, target=None):
        if threading.get_ident() != self._thread:
            return None
        if name in self._names or name.startswith(self._subtrees):
            raise ImportError(f"vmn autolog discovery skips {name}", name=name)
        return None


@contextlib.contextmanager
def _refusing_imports(names):
    finder = _RefuseImports(names)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


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


SKLEARN = _adapter("sklearn", _discover_sklearn)
XGBOOST = _adapter("xgboost", _discover_xgboost)
