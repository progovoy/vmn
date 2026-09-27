"""Driver-side Ray Tune integration for vmn experiment tracking.

``import vmn_exp.integrations.ray_tune`` never imports ray itself.  The
:class:`VmnTuneCallback` subclass (which inherits from ``ray.tune.Callback``)
is built lazily — call :func:`make_callback` from code that already has ray
available, or access the module attribute ``VmnTuneCallback`` the same way.

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

from version_stamp.exp import start_run

_LOGGER = logging.getLogger(__name__)

# Ray injects these keys into every result dict.  They are timing / bookkeeping
# values, not the user's objective metrics, so they are dropped before the
# remaining values are forwarded to the SDK (which handles its own coercion).
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
        "training_iteration",  # used as step counter, not a metric
        "warmup_time",
    }
)

# Cached ray.tune.Callback subclass; built once on first make_callback() call.
_callback_class: Any = None


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
    """Drop Ray bookkeeping keys; the SDK coerces and validates the rest."""
    return {k: v for k, v in result.items() if k not in _RAY_BOOKKEEPING_KEYS}


def _make_callback_class() -> Any:
    """Import ray.tune and build (or return the cached) VmnTuneCallback class."""
    global _callback_class
    if _callback_class is None:
        import ray.tune  # noqa: PLC0415 — intentionally deferred

        class VmnTuneCallback(ray.tune.Callback):
            """Bridges Ray Tune driver callback hooks to a :class:`TuneRecorder`.

            Construct with a recorder::

                recorder = TuneRecorder(app_name="my_app")
                tune.run(..., callbacks=[VmnTuneCallback(recorder)])
            """

            def __init__(self, rec: "TuneRecorder") -> None:
                self._recorder = rec

            def on_trial_start(self, iteration, trials, trial, **info):
                self._recorder.on_trial_start(trial.trial_id, trial.config)

            def on_trial_result(self, iteration, trials, trial, result, **info):
                self._recorder.on_trial_result(trial.trial_id, result)

            def on_trial_complete(self, iteration, trials, trial, **info):
                self._recorder.on_trial_complete(trial.trial_id)

            def on_trial_error(self, iteration, trials, trial, **info):
                self._recorder.on_trial_error(trial.trial_id)

            def on_experiment_end(self, trials, **info):
                self._recorder.finish()

        _callback_class = VmnTuneCallback
    return _callback_class


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
        outer = self._ensure_outer()
        flat_params = _flatten_dict(config) if config else None

        inner = start_run(
            app_name=self._app_name,
            params=flat_params,
            parent=outer.id,
            nested=True,
            name=trial_id,
            **self._kwargs,
        )
        self._trial_runs[trial_id] = inner

    def on_trial_result(self, trial_id: str, result: Dict[str, Any]) -> None:
        """Log metrics from a Ray result dict to the trial's inner run.

        ``training_iteration`` (when present) is used as the step counter.
        Ray bookkeeping keys are silently dropped; the SDK handles coercion and
        drops booleans / non-numeric values.
        """
        inner = self._trial_runs.get(trial_id)
        if inner is None:
            _LOGGER.warning("on_trial_result: unknown trial_id %r — ignored", trial_id)
            return

        step = result.get("training_iteration")
        filtered = _filter_bookkeeping(result)
        if filtered:
            inner.log_metrics(filtered, step=step)

    def on_trial_complete(self, trial_id: str) -> None:
        """Mark *trial_id*'s inner run as succeeded (exit_code=0)."""
        inner = self._trial_runs.pop(trial_id, None)
        if inner is None:
            _LOGGER.debug("on_trial_complete: trial %r not tracked — skipped", trial_id)
            return
        inner.finish(exit_code=0)

    def on_trial_error(self, trial_id: str) -> None:
        """Mark *trial_id*'s inner run as failed (exit_code=1)."""
        inner = self._trial_runs.pop(trial_id, None)
        if inner is None:
            _LOGGER.debug("on_trial_error: trial %r not tracked — skipped", trial_id)
            return
        inner.finish(exit_code=1)

    def _close_all(self, exit_code: int) -> None:
        """Finish all open trial runs with *exit_code* and clear the registry."""
        for tid, inner in list(self._trial_runs.items()):
            if exit_code == 0:
                _LOGGER.warning("finish(): trial %r still open — closing as succeeded", tid)
            inner.finish(exit_code=exit_code)
        self._trial_runs.clear()

    def finish(self) -> None:
        """Finish any open trial runs and the outer run.

        Idempotent: safe to call more than once (already-finished runs are
        no-ops inside ``Run.finish``).
        """
        self._close_all(exit_code=0)
        if self._outer_run is not None:
            self._outer_run.finish(exit_code=0)
            self._outer_run = None

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "TuneRecorder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self._close_all(exit_code=1)
            if self._outer_run is not None:
                self._outer_run.finish(exit_code=1)
                self._outer_run = None
        else:
            self.finish()


# ---------------------------------------------------------------------------
# VmnTuneCallback — lazy, never imports ray at module load time
# ---------------------------------------------------------------------------


def make_callback(recorder: TuneRecorder) -> Any:
    """Return a ``ray.tune.Callback`` instance that drives *recorder*.

    Importing this module does **not** import ray.  Calling ``make_callback``
    will import ``ray.tune`` and raise ``ImportError`` if ray is not installed.

    The returned callback maps Ray's five driver-side hooks to the recorder::

        on_trial_start   → recorder.on_trial_start(trial_id, config)
        on_trial_result  → recorder.on_trial_result(trial_id, result)
        on_trial_complete→ recorder.on_trial_complete(trial_id)
        on_trial_error   → recorder.on_trial_error(trial_id)
        on_experiment_end→ recorder.finish()
    """
    return _make_callback_class()(recorder)


def __getattr__(name: str) -> Any:
    """Lazy module attribute: ``VmnTuneCallback`` builds the class on demand."""
    if name == "VmnTuneCallback":
        return _make_callback_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
