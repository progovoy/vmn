"""Autolog adapter for Lightning, under both of its import names.

``Trainer.fit(model, ...)`` trains its first argument, not its ``self``, and
reports metrics on the trainer; the model is saved as a Lightning checkpoint.
"""
import weakref

from version_stamp.exp.autolog_adapter import (
    _LOGGER,
    _adapter,
    _fit_owners,
    _no_params,
)


def _discover_lightning(module):
    """``Trainer.fit``, under either of Lightning's two import names.

    ``lightning.pytorch.Trainer`` and ``pytorch_lightning.Trainer`` are distinct
    class objects from two mirrored packages, so each import name really does
    need its own patch — unlike keras/tensorflow, which share one class.
    """
    trainer = getattr(module, "Trainer", None) or getattr(
        getattr(module, "pytorch", None), "Trainer", None
    )
    return _fit_owners([trainer])


def _lightning_module(call):
    """``Trainer.fit(model, ...)`` trains its first argument, not its ``self``."""
    return call.args[0] if call.args else call.kwargs.get("model")


def _lightning_params(call):
    """The trainer's budget, then the module's ``hparams``, which win on a clash."""
    trainer = call.instance
    params = {
        "max_epochs": getattr(trainer, "max_epochs", None),
        "precision": getattr(trainer, "precision", None),
    }
    hparams = getattr(_lightning_module(call), "hparams", None)
    params.update(dict(hparams or {}))
    return params


def _lightning_metrics(call):
    """``trainer.callback_metrics`` — what the module logged, as it stood at the end."""
    return dict(getattr(call.instance, "callback_metrics", None) or {})


# Trainers already warned about, so a multi-fit script warns once per trainer.
_DDP_WARNED = weakref.WeakSet()


def _save_lightning_checkpoint(call, subject, base):
    """Lightning's own checkpoint, which restores through ``load_from_checkpoint``.

    Skipped under multi-process training: ``save_checkpoint`` ends in a barrier
    every rank must reach, and only the rank that opened a run gets here — so
    calling it would hang that rank until the process-group timeout.
    """
    trainer = call.instance
    world_size = getattr(trainer, "world_size", 1) or 1
    if world_size > 1:
        if trainer not in _DDP_WARNED:
            _DDP_WARNED.add(trainer)
            _LOGGER.warning(
                "vmn autolog: not saving the Lightning model (world_size=%s); "
                "save_checkpoint must run on every rank — log it yourself with "
                "run.log_artifact() after trainer.save_checkpoint()",
                world_size,
            )
        return None
    path = base + ".ckpt"
    trainer.save_checkpoint(path)
    return path


LIGHTNING = _adapter(
    "lightning",
    _discover_lightning,
    subject=_lightning_module,
    params=_lightning_params,
    metrics=_lightning_metrics,
    save=_save_lightning_checkpoint,
    fitted_params=_no_params,
)
