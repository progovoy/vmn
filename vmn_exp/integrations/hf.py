"""HuggingFace Transformers callback for vmn experiment tracking.

Importing this module does NOT import transformers.  ``VmnCallback`` is
assembled lazily the first time the name is accessed (via ``__getattr__``),
so the heavy ``transformers`` package is only loaded when the user
explicitly uses the callback or autolog patches a Trainer.

Usage (manual)::

    from vmn_exp.integrations.hf import VmnCallback
    # transformers is imported here, not at the line above

    trainer = Trainer(..., callbacks=[VmnCallback()])

Usage (via autolog)::

    from vmn_exp.sdk import autolog, start_run
    autolog()  # registers HF patch; transformers not imported yet
    with start_run("my_app") as run:
        Trainer(...).train()  # VmnCallback added automatically
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import transformers  # noqa: F401 — type-checking only

_LOGGER = logging.getLogger("vmn_exp.sdk.autolog")

# Cached class object so we build it once.
_vmn_callback_class = None


def _build_vmn_callback():
    global _vmn_callback_class
    if _vmn_callback_class is not None:
        return _vmn_callback_class

    import transformers  # noqa: PLC0415 — intentionally lazy

    from vmn_exp.integrations.hf_core import (
        checkpoint_artifacts,
        is_world_process_zero,
        params_from,
        rewrite_logs,
    )

    # Import the context module once; call its attribute dynamically so that
    # mock.patch("vmn_exp.sdk.context.current_run", ...) works in tests.
    try:
        import vmn_exp.sdk.context as _context_mod

        def _get_current_run():
            return _context_mod.current_run()

    except Exception:
        _LOGGER.debug("vmn autolog hf: current_run unavailable", exc_info=True)
        _get_current_run = lambda: None  # noqa: E731

    def _run_for_world_process(state):
        """Return the active run if this is the world process zero, else None."""
        if not is_world_process_zero(state):
            return None
        return _get_current_run()

    class VmnCallback(transformers.TrainerCallback):
        """Records params, metrics and optional checkpoints into the active vmn run.

        Records nothing when there is no open run — safe to attach even when
        the code runs outside of a ``start_run()`` context.

        Args:
            log_checkpoints: If ``True``, call ``run.log_artifact`` for each
                ``checkpoint-<N>`` directory on every ``on_save`` event.
                Off by default because checkpoints are large.
        """

        def __init__(self, log_checkpoints: bool = False) -> None:
            self._log_checkpoints = log_checkpoints

        # ------------------------------------------------------------------
        # TrainerCallback hooks
        # ------------------------------------------------------------------

        def on_train_begin(self, args, state, control, model=None, **kwargs):
            run = _run_for_world_process(state)
            if run is None:
                return
            try:
                args_dict = args.to_dict() if hasattr(args, "to_dict") else {}
                config_dict = None
                default_dict = None
                if model is not None:
                    cfg = getattr(model, "config", None)
                    if cfg is not None and hasattr(cfg, "to_dict"):
                        config_dict = cfg.to_dict()
                        try:
                            default_dict = type(cfg)().to_dict()
                        except Exception:
                            _LOGGER.debug(
                                "vmn autolog hf: could not build default config",
                                exc_info=True,
                            )
                run.log_params(params_from(args_dict, config_dict, default_dict))
            except Exception:
                _LOGGER.debug(
                    "vmn autolog hf: on_train_begin failed", exc_info=True
                )

        def on_log(self, args, state, control, logs=None, **kwargs):
            run = _run_for_world_process(state)
            if run is None:
                return
            try:
                metrics = rewrite_logs(logs or {})
                if metrics:
                    run.log_metrics(
                        metrics, step=getattr(state, "global_step", None)
                    )
            except Exception:
                _LOGGER.debug("vmn autolog hf: on_log failed", exc_info=True)

        def on_save(self, args, state, control, **kwargs):
            if not self._log_checkpoints:
                return
            run = _run_for_world_process(state)
            if run is None:
                return
            try:
                output_dir = getattr(args, "output_dir", None)
                if output_dir:
                    for path in checkpoint_artifacts(output_dir):
                        run.log_artifact(path)
            except Exception:
                _LOGGER.debug("vmn autolog hf: on_save failed", exc_info=True)

    _vmn_callback_class = VmnCallback
    return _vmn_callback_class


def __getattr__(name: str):
    if name == "VmnCallback":
        return _build_vmn_callback()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
