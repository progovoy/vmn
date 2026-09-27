"""Autolog adapter for HuggingFace Transformers Trainer.

Uses ``watch=("transformers.trainer",)`` so the patch fires only when the
trainer submodule is first imported — ``import transformers`` alone (which is
lazy-loaded) does not trigger it.  ``method_owners`` locates ``Trainer.train``
(the training entry point), and ``instrument`` injects a :class:`VmnCallback`
into the Trainer instance before training starts.

All logging is done by the callback; the standard ``_wrap_fit`` machinery's
params/metrics hooks are disabled (``_no_params`` / ``_no_metrics``).
"""
from __future__ import annotations

from version_stamp.exp.autolog_adapter import (
    _LOGGER,
    _adapter,
    _no_metrics,
    _no_params,
    _no_save,
    _no_series,
)


def _method_owners_hf(trainer_module):
    """Locate ``Trainer.train`` in the trainer submodule.

    Using ``method_owners`` rather than ``discover`` keeps the selection of
    ``train`` (not ``fit``) explicit and avoids the ``_fit_owners`` heuristic.
    """
    trainer_cls = getattr(trainer_module, "Trainer", None)
    if trainer_cls is None:
        _LOGGER.debug("vmn autolog: transformers.trainer.Trainer not found")
        return []
    # Patch Trainer.train — the method users call to start training.
    if "train" not in vars(trainer_cls):
        _LOGGER.debug(
            "vmn autolog: Trainer.train not in __dict__; skipping HF patch"
        )
        return []
    return [(trainer_cls, "train")]


def _maybe_add_callback(trainer) -> None:
    """Add a VmnCallback to *trainer* unless one is already present.

    String comparison avoids importing ``VmnCallback`` (and thus transformers)
    just to check presence — at this point transformers is already imported,
    but keeping the check import-free makes the guard unconditionally cheap.
    """
    cb_handler = getattr(trainer, "callback_handler", None)
    if cb_handler is not None:
        for cb in getattr(cb_handler, "callbacks", []):
            if type(cb).__name__ == "VmnCallback":
                return  # already has one

    from vmn_exp.integrations import hf as hf_mod

    VmnCallback = hf_mod.VmnCallback  # triggers lazy build if needed
    try:
        trainer.add_callback(VmnCallback())
    except Exception:
        _LOGGER.debug("vmn autolog: could not add VmnCallback", exc_info=True)


def _hf_instrument(call, run):
    """Inject a VmnCallback into the Trainer before training starts.

    The callback handles all per-step metric logging via ``on_log`` and
    param logging via ``on_train_begin``.  The standard ``_wrap_fit``
    metrics/params hooks are no-ops so nothing is double-counted.
    """
    _maybe_add_callback(call.instance)
    return call


#: Adapter registered under the ``"transformers"`` import name.
TRANSFORMERS = _adapter(
    "transformers",
    params=_no_params,
    metrics=_no_metrics,
    series=_no_series,
    save=_no_save,
    instrument=_hf_instrument,
    fitted_params=_no_params,
    watch=("transformers.trainer",),
    method_owners=_method_owners_hf,
)
