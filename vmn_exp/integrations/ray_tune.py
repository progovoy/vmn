"""Driver-side Ray Tune integration for vmn experiment tracking.

``import vmn_exp.integrations.ray_tune`` never imports ray itself.  Call
:func:`make_callback` from code that already has ray available to get a
``ray.tune.Callback`` instance.

Typical driver-side usage::

    from vmn_exp.integrations.ray_tune import TuneRecorder, make_callback
    import ray.tune as tune

    recorder = TuneRecorder(app_name="my_app", experiment_name="lr sweep")
    analysis = tune.run(
        trainable,
        config={"lr": tune.grid_search([1e-3, 3e-4])},
        callbacks=[make_callback(recorder)],
    )
    recorder.finish()

One outer run is created on the first ``on_trial_start``.  Each trial maps to
one inner run with ``parent=outer.id`` and ``nested=True``.  Decision D20:
worker-side autolog is deferred; this is driver-only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

_LOGGER = logging.getLogger(__name__)

# Ray injects these keys into every result dict.  They are timing / bookkeeping
# values, not objective metrics, so they are stripped before logging.
_RAY_BOOKKEEPING_KEYS = frozenset(
    {
        "config",
        "date",
        "done",
        "experiment_id",
        "hostname",
        "iterations_since_restore",
        "node_ip",
        "num_errored_trials",
        "num_healthy_trials",
        "num_pending_trials",
        "num_running_trials",
        "num_terminated_trials",
        "pid",
        "time_since_restore",
        "time_this_iter_s",
        "time_total_s",
        "timestamp",
        "timesteps_since_restore",
        "trial_id",
        "training_iteration",  # used as step, not logged as a metric
        "warmup_time",
    }
)


def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Return a flat copy of *d* with nested keys joined by '.'.

    >>> _flatten_dict({"model": {"depth": 3}, "lr": 0.01})
    {'model.depth': 3, 'lr': 0.01}
    """
    out: Dict[str, Any] = {}
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            out.update(_flatten_dict(value, full_key))
        else:
            out[full_key] = value
    return out


def _filter_bookkeeping(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return *result* with Ray bookkeeping keys removed.

    Numeric coercion and bool/non-numeric dropping are left to the SDK's
    ``log_metrics`` → ``sanitize_entry`` path, which already handles them.
    """
    return {k: v for k, v in result.items() if k not in _RAY_BOOKKEEPING_KEYS}


class TuneRecorder:
    """Record a Ray Tune experiment as an outer + inner run tree.

    One outer run is created on the first trial start.  Each trial maps to one
    inner run with ``parent=outer.id`` and ``nested=True``.

    Args:
        app_name: vmn app name.  ``None`` resolves it from the current repo or
            from ``VMN_APP_NAME``.
        experiment_name: Human-readable name stored as the outer run's ``name``
            field (shown by ``vmn exp list``).
        **start_run_kwargs: Forwarded verbatim to every ``start_run()`` call.
            Useful for ``storage=``, ``snapshot=False``, ``tags=``, etc.
    """

    def __init__(
        self,
        app_name: Optional[str] = None,
        experiment_name: Optional[str] = None,
        **start_run_kwargs: Any,
    ) -> None:
        self._app_name = app_name
        self._experiment_name = experiment_name
        self._kwargs = start_run_kwargs
        self._outer_run: Any = None
        self._trial_runs: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Outer run management
    # ------------------------------------------------------------------

    def _ensure_outer(self) -> Any:
        """Return the outer run, creating it now if it has not been yet."""
        if self._outer_run is None:
            from vmn_exp.sdk import start_run

            self._outer_run = start_run(
                app_name=self._app_name,
                name=self._experiment_name,
                **self._kwargs,
            )
        return self._outer_run

    # ------------------------------------------------------------------
    # Trial lifecycle hooks
    # ------------------------------------------------------------------

    def on_trial_start(self, trial_id: str, config: Dict[str, Any]) -> None:
        """Open an inner run for *trial_id*, parented to the outer run.

        *config* is flattened (nested dicts joined with '.') and recorded as
        the trial run's params.
        """
        from vmn_exp.sdk import start_run

        outer = self._ensure_outer()
        flat_params = _flatten_dict(config) if config else None
        inner = start_run(
            app_name=self._app_name,
            params=flat_params or None,
            parent=outer.id,
            nested=True,
            name=trial_id,
            **self._kwargs,
        )
        self._trial_runs[trial_id] = inner

    def on_trial_result(self, trial_id: str, result: Dict[str, Any]) -> None:
        """Log numeric metrics from a Ray result dict to the trial's inner run.

        ``training_iteration`` (when present) is used as the step counter.
        Ray bookkeeping keys are silently dropped.
        """
        inner = self._trial_runs.get(trial_id)
        if inner is None:
            _LOGGER.warning("on_trial_result: unknown trial_id %r — ignored", trial_id)
            return

        step = result.get("training_iteration")
        metrics = _filter_bookkeeping(result)
        if metrics:
            inner.log_metrics(metrics, step=step)

    def on_trial_complete(self, trial_id: str) -> None:
        """Mark *trial_id*'s inner run as succeeded (exit_code=0)."""
        self._finish_trial(trial_id, exit_code=0)

    def on_trial_error(self, trial_id: str) -> None:
        """Mark *trial_id*'s inner run as failed (exit_code=1)."""
        self._finish_trial(trial_id, exit_code=1)

    def _finish_trial(self, trial_id: str, exit_code: int) -> None:
        inner = self._trial_runs.pop(trial_id, None)
        if inner is None:
            _LOGGER.debug("_finish_trial: trial %r not tracked — skipped", trial_id)
            return
        inner.finish(exit_code=exit_code)

    def finish(self) -> None:
        """Finish any open trial runs and the outer run.

        Idempotent: safe to call more than once.
        """
        self._close_all(exit_code=0)

    def _close_all(self, exit_code: int) -> None:
        """Finish every open trial run with *exit_code*, then the outer run."""
        for tid, inner in list(self._trial_runs.items()):
            if exit_code == 0:
                _LOGGER.warning("finish(): trial %r still open — closing as succeeded", tid)
            inner.finish(exit_code=exit_code)
        self._trial_runs.clear()

        if self._outer_run is not None:
            self._outer_run.finish(exit_code=exit_code)
            self._outer_run = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "TuneRecorder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._close_all(exit_code=1 if exc_type is not None else 0)


# ---------------------------------------------------------------------------
# VmnTuneCallback — lazy, never imports ray at module load time
# ---------------------------------------------------------------------------


def _build_callback_class() -> Any:
    """Import ray.tune and return the VmnTuneCallback class (cached on module)."""
    cached = globals().get("_VmnTuneCallbackClass")
    if cached is not None:
        return cached

    import ray.tune  # noqa: PLC0415  — intentionally deferred

    class VmnTuneCallback(ray.tune.Callback):
        """Bridges Ray Tune driver callback hooks to :class:`TuneRecorder`.

        Construct with a recorder and pass to ``tune.run``::

            recorder = TuneRecorder(app_name="my_app")
            tune.run(..., callbacks=[make_callback(recorder)])
        """

        def __init__(self, rec: "TuneRecorder") -> None:
            self._rec = rec

        def on_trial_start(self, iteration, trials, trial, **info):
            self._rec.on_trial_start(trial.trial_id, trial.config)

        def on_trial_result(self, iteration, trials, trial, result, **info):
            self._rec.on_trial_result(trial.trial_id, result)

        def on_trial_complete(self, iteration, trials, trial, **info):
            self._rec.on_trial_complete(trial.trial_id)

        def on_trial_error(self, iteration, trials, trial, **info):
            self._rec.on_trial_error(trial.trial_id)

        def on_experiment_end(self, trials, **info):
            self._rec.finish()

    globals()["_VmnTuneCallbackClass"] = VmnTuneCallback
    return VmnTuneCallback


def make_callback(recorder: TuneRecorder) -> Any:
    """Return a ``ray.tune.Callback`` instance that drives *recorder*.

    Importing this module does **not** import ray.  Calling ``make_callback``
    will import ``ray.tune`` and raise ``ImportError`` if ray is not installed.
    """
    return _build_callback_class()(recorder)


def __getattr__(name: str) -> Any:
    """Lazy module attribute: ``VmnTuneCallback`` is the callback class."""
    if name == "VmnTuneCallback":
        return _build_callback_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
