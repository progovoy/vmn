"""Gradient/parameter histograms of a plain torch model (like ``wandb.watch``).

Importing this module does NOT import torch::

    from vmn_exp.integrations.torch_watch import watch
    with start_run("my_app") as run:
        watcher = watch(model, log="gradients", freq=1000)
        for batch in loader:
            loss = model(batch).sum(); loss.backward(); opt.step()
        watcher.remove()  # or unwatch(model); logs what is still pending

Every *freq*-th forward call in training mode (the watch *step*) logs
``<prefix>parameters/<param>`` histograms and arms the gradient hooks; the
gradients of that pass are logged as ``<prefix>gradients/<param>`` at the
next forward call (or :meth:`Watcher.flush`). Gradient hooks exist only
while a step is armed; they may run on autograd engine threads, so they only
stash their histogram; every
``log_histogram`` call happens on the training thread. The run is ``run`` or
:func:`~vmn_exp.sdk.context.current_run` at the forward call; without one
(e.g. ranks > 0) nothing is recorded. A failing hook never breaks training.
"""
import logging
import weakref

from vmn_exp.core.best_effort import quiet
from vmn_exp.core.histogram import equal_edges, positive_int, value_range

_LOGGER = logging.getLogger("vmn_exp.integrations.torch_watch")
_GUARD = quiet(_LOGGER)
_MODES = {"gradients": (True, False), "parameters": (False, True), "all": (True, True)}
_WATCHERS = weakref.WeakKeyDictionary()  # model -> its Watcher


def _counts_of(flat, bins, lo, hi):
    import torch

    try:
        return torch.histc(flat, bins=bins, min=lo, max=hi)
    except (RuntimeError, NotImplementedError):  # e.g. histc unsupported on MPS
        return torch.histc(flat.cpu(), bins=bins, min=lo, max=hi)


def _tensor_histogram(tensor, bins):
    """``{"bins", "counts"}`` of *tensor*'s finite values, computed on its
    device (like :func:`vmn_exp.core.histogram.histogram`), or None."""
    import torch

    flat = tensor.detach().reshape(-1).float()
    flat = flat[torch.isfinite(flat)]
    if flat.numel() == 0:
        return None
    lo, hi = value_range(*(float(v) for v in torch.stack(torch.aminmax(flat)).tolist()))
    counts = _counts_of(flat, bins, lo, hi).tolist()
    return {"bins": equal_edges(lo, hi, bins), "counts": [int(c) for c in counts]}


class Watcher:
    """The hooks :func:`watch` put on a model; :meth:`remove` takes them off."""

    def __init__(self, model, log, freq, bins, run, prefix):
        self._grads, self._params = _MODES[log]
        self._freq, self._bins, self._run, self._prefix = freq, bins, run, prefix
        self._model = weakref.ref(model)
        self._calls = 0
        self._armed = None  # (run, step) whose gradients are being captured
        self._pending = {}  # param name -> gradient histogram
        self._grad_handles = []  # present only while armed
        self._forward = model.register_forward_pre_hook(self._on_forward)

    def _arm(self, run, model):
        self._armed = (run, self._calls)
        self._grad_handles = [
            p.register_hook(self._grad_hook(name))
            for name, p in model.named_parameters() if p.requires_grad
        ]

    def _grad_hook(self, name):
        def hook(grad):
            _GUARD("gradient histogram", self._stash, name, grad)

        return hook

    def _stash(self, name, grad):
        binned = _tensor_histogram(grad, self._bins)
        if binned is not None:
            self._pending[name] = binned

    def _on_forward(self, module, _inputs):
        if module.training:
            _GUARD("watch step", self._step, module)

    def _step(self, model):
        self.flush()
        self._calls += 1
        if self._calls % self._freq:
            return
        run = self._run or _current_run()
        if run is None:
            return
        if self._params:
            self._log_parameters(run, model)
        if self._grads:
            self._arm(run, model)

    def _log_parameters(self, run, model):
        import torch

        with torch.no_grad():
            for name, param in model.named_parameters():
                binned = _tensor_histogram(param, self._bins)
                if binned is not None:
                    self._log(run, "parameters", name, binned, self._calls)

    def _log(self, run, kind, name, binned, step):
        run.log_histogram(f"{self._prefix}{kind}/{name}", binned, step=step)

    def flush(self):
        """Log the gradient histograms captured since the last armed step."""
        if self._armed is None:
            return
        (run, step), self._armed = self._armed, None
        for handle in self._grad_handles:
            handle.remove()
        self._grad_handles = []
        pending, self._pending = self._pending, {}
        for name, binned in pending.items():
            _GUARD("gradient log", self._log, run, "gradients", name, binned, step)

    def remove(self):
        """Flush, then detach every hook; idempotent."""
        self.flush()
        self._forward.remove()
        model = self._model()
        if model is not None and _WATCHERS.get(model) is self:
            del _WATCHERS[model]


def _current_run():
    from vmn_exp.sdk.context import current_run

    return current_run()


def watch(model, log="gradients", freq=1000, bins=64, run=None, prefix=""):
    """Log *model*'s gradient and/or parameter histograms every *freq* steps.

    *log* is ``"gradients"``, ``"parameters"`` or ``"all"``. Watching a model
    again replaces its previous watcher. Returns the :class:`Watcher`.
    """
    if log not in _MODES:
        raise ValueError(f"log must be one of {sorted(_MODES)}, got {log!r}")
    positive_int(freq, "freq")
    positive_int(bins, "bins")
    unwatch(model)
    watcher = Watcher(model, log, freq, bins, run, prefix)
    _WATCHERS[model] = watcher
    return watcher


def unwatch(model_or_watcher):
    """Remove the hooks of a :class:`Watcher`, or of the one watching a model."""
    if isinstance(model_or_watcher, Watcher):
        watcher = model_or_watcher
    else:
        watcher = _WATCHERS.get(model_or_watcher)
    if watcher is not None:
        watcher.remove()
