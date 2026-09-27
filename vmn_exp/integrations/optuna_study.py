"""Optuna integration for vmn experiment tracking.

``start_study_run(study)`` opens an outer run for the Optuna study and returns
a :class:`StudyTracker`.  Call ``tracker.wrap(objective)`` to get an objective
that records each trial as an inner run, then pass that to
``study.optimize()``.  Call ``tracker.finish()`` after optimizing to record the
best result on the outer run.

Design notes
------------
* Each trial opens its own inner run with ``parent=outer.id`` (explicit) and
  ``nested=True`` (bypasses the re-entry guard that would fire when the outer
  run is still active on the same thread).  With ``n_jobs>1``, Optuna runs
  trials in worker threads that each copy the parent's ContextVar state, so
  they start with the outer run as their current_run — the same guard applies.
  Explicit ``parent=`` wins over everything; ``nested=True`` only silences the
  guard.

* Intermediate values logged via ``trial.report(value, step)`` are captured
  by wrapping the trial's ``.report`` method so they land as a metric series
  (key ``"intermediate"``) without any post-hoc reading of internal state.

* Pruned trials (``optuna.TrialPruned``) are recorded as succeeded with tag
  ``state=pruned`` and ``TrialPruned`` is re-raised so Optuna marks the trial
  as PRUNED.

* Other exceptions are recorded as failed and re-raised so Optuna's ``catch``
  mechanism can handle them.

* ``autolog()`` inside the objective lands in the trial run automatically:
  ``current_run()`` on the trial's thread returns the trial's run because
  ``start_run`` sets the ContextVar for that thread.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)


def start_study_run(study, app_name: Optional[str] = None, **start_run_kwargs):
    """Open an outer experiment run for an Optuna study.

    Args:
        study: an ``optuna.Study`` object.
        app_name: experiment app name; resolved from the git checkout when
            ``None``.
        **start_run_kwargs: forwarded verbatim to ``start_run()`` for the
            outer run.  ``name`` defaults to ``study.study_name``.

    Returns:
        A :class:`StudyTracker` with ``wrap(objective)`` and ``finish()``.
    """
    try:
        import optuna  # noqa: F401 – verify it is available
    except ImportError as exc:
        raise ImportError(
            "optuna is required: pip install optuna"
        ) from exc

    from vmn_exp.sdk import start_run

    params = _study_params(study)
    name = start_run_kwargs.pop("name", study.study_name or "optuna-study")
    outer = start_run(app_name, name=name, params=params, **start_run_kwargs)
    return StudyTracker(outer, study)


class StudyTracker:
    """Tracks an Optuna study as an outer run with per-trial inner runs.

    Returned by :func:`start_study_run`.
    """

    def __init__(self, outer_run, study):
        self._outer = outer_run
        self._study = study

    def wrap(self, objective: Callable) -> Callable:
        """Return a wrapped objective that records each trial as an inner run.

        The wrapper:
        * opens an inner run with ``parent=outer.id`` and ``nested=True``;
        * logs ``trial.params`` as params;
        * logs the return value(s) as ``"objective"`` (single) or
          ``"objective_<i>"`` (multi-objective);
        * captures intermediate values from ``trial.report`` as the metric
          series ``"intermediate"``;
        * tags ``trial.number``, ``state=pruned`` for pruned trials;
        * records pruned trials as succeeded, failed trials as failed.
        """
        import optuna as _optuna
        from vmn_exp.sdk import start_run as _sr

        TrialPruned = _optuna.TrialPruned
        outer_id = self._outer.id
        app_name = self._outer.app_name

        def _wrapped(trial):
            run = _sr(
                app_name,
                parent=outer_id,
                nested=True,
                tags={"trial_number": str(trial.number)},
                snapshot=False,
            )
            _install_report_hook(trial, run)
            try:
                result = objective(trial)
            except TrialPruned:
                run.set_tag("state", "pruned")
                _log_trial_params(trial, run)
                run.finish(exit_code=0)
                raise  # let Optuna mark the trial PRUNED
            except Exception:
                run.finish(exit_code=1)
                raise
            else:
                _log_trial_params(trial, run)
                _log_trial_result(result, run)
                run.finish(exit_code=0)
                return result

        return _wrapped

    def finish(self):
        """Log best trial result on the outer run and close it."""
        _log_best(self._outer, self._study)
        self._outer.finish()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _study_params(study) -> dict:
    """Sampler/pruner class names and direction(s) for the outer run."""
    params: dict[str, Any] = {}
    if study.sampler is not None:
        params["sampler"] = type(study.sampler).__name__
    if study.pruner is not None:
        params["pruner"] = type(study.pruner).__name__
    directions = getattr(study, "directions", None)
    if directions:
        if len(directions) == 1:
            params["direction"] = directions[0].name.lower()
        else:
            params["directions"] = [d.name.lower() for d in directions]
    return params


def _install_report_hook(trial, run) -> None:
    """Wrap ``trial.report`` to log each intermediate value as a metric series."""
    original = trial.report

    def _hooked(value, step):
        original(value, step)
        try:
            run.log_metric("intermediate", float(value), step=step)
        except Exception:
            pass

    trial.report = _hooked


def _log_trial_params(trial, run) -> None:
    if trial.params:
        run.log_params(trial.params)


def _log_trial_result(result, run) -> None:
    if isinstance(result, (list, tuple)):
        for i, v in enumerate(result):
            try:
                run.log_metric(f"objective_{i}", float(v))
            except (TypeError, ValueError):
                pass
    else:
        try:
            run.log_metric("objective", float(result))
        except (TypeError, ValueError):
            pass


def _log_best(outer_run, study) -> None:
    """Log the best trial's value and params on the outer run after optimizing."""
    if len(getattr(study, "directions", [])) > 1:
        # Multi-objective: no single best value; record Pareto front size
        try:
            best_trials = study.best_trials
            if best_trials:
                outer_run.log_params({"best_n_pareto_trials": len(best_trials)})
        except Exception:
            pass
        return
    try:
        best = study.best_trial
    except ValueError:
        return  # no completed trials
    try:
        if best.value is not None:
            outer_run.log_metric("best_value", float(best.value))
        if best.params:
            outer_run.log_params({f"best_{k}": v for k, v in best.params.items()})
    except Exception as exc:
        _LOGGER.debug("vmn: could not log best trial: %s", exc)
