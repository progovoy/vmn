"""Autolog adapters for LightGBM's and CatBoost's scikit-learn wrappers.

Both keep the default ``get_params()`` and add three things:

* metrics are the training ``score`` only. Their ``best_score_`` is the
  eval-set results, not a cross-validated score, so the default
  ``best_cv_score`` would publish a wrong name;
* the per-iteration eval results become one series per dataset and metric,
  ``<dataset>_<metric>``; the last point is the final value;
* ``best_iteration`` once training has one.

The native ``lightgbm.train`` / ``catboost.train`` APIs are left alone, for the
reason ``_discover_xgboost`` gives. CatBoost's ``get_params()`` returns only the
explicitly set parameters, so its params row is shorter than scikit-learn's.
"""
from vmn_exp.sdk.autolog_adapter import _adapter, _fit_owners, _training_score


def _discover(*names):
    def discover(module):
        return _fit_owners([getattr(module, name, None) for name in names])

    return discover


def _eval_series(results):
    return {
        f"{dataset}_{metric}": list(points)
        for dataset, metrics in (results or {}).items()
        for metric, points in metrics.items()
    }


def _lightgbm_series(call):
    return _eval_series(getattr(call.instance, "evals_result_", None))


def _lightgbm_best_iteration(call):
    """LightGBM reports 0 when no early stopping picked an iteration."""
    best = getattr(call.instance, "best_iteration_", None)
    return {"best_iteration": best} if best else {}


def _catboost_series(call):
    return _eval_series(call.instance.get_evals_result())


def _catboost_best_iteration(call):
    best = call.instance.get_best_iteration()
    return {} if best is None else {"best_iteration": best}


def _catboost_save(call, subject, base):
    path = base + ".cbm"
    subject.save_model(path)
    return path


LIGHTGBM = _adapter(
    "lightgbm",
    _discover("LGBMClassifier", "LGBMRegressor", "LGBMRanker"),
    metrics=_training_score,
    series=_lightgbm_series,
    fitted_params=_lightgbm_best_iteration,
)
CATBOOST = _adapter(
    "catboost",
    _discover("CatBoostClassifier", "CatBoostRegressor", "CatBoostRanker", "CatBoost"),
    metrics=_training_score,
    series=_catboost_series,
    fitted_params=_catboost_best_iteration,
    save=_catboost_save,
)
