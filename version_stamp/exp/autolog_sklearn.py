"""Autolog adapters for scikit-learn and xgboost's scikit-learn wrappers.

Both use the adapter defaults (``get_params()``, ``score()``, a pickle), so all
they add is where ``fit`` lives.
"""
from version_stamp.exp.autolog_adapter import _adapter, _fit_owners, _import


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


SKLEARN = _adapter("sklearn", _discover_sklearn)
XGBOOST = _adapter("xgboost", _discover_xgboost)
