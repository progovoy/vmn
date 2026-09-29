#!/usr/bin/env python3
"""``Run.log_metric(s)`` and ``Run.step``: metrics entries, auto-stepped.

Mixed into :class:`~vmn_exp.sdk.run.Run`, which provides ``_steps`` (a
:class:`~vmn_exp.sdk.steps.StepCounter`), ``_log_buffer`` and ``_append``.
"""
from vmn_exp.core.values import sanitize_entry
from vmn_exp.core.writer import create_log_entry


class RunMetrics:
    @property
    def step(self):
        """The step the next ``log_metrics`` without ``step=`` records."""
        return self._steps.next

    def log_metric(self, key, value, step=None, commit=True):
        self.log_metrics({key: value}, step=step, commit=commit)

    def log_metrics(self, mapping, step=None, commit=True):
        """Record *mapping* at *step* (default: ``run.step``, then advanced).

        An explicit step raises ``run.step`` past it, never lowers it.
        ``commit=False`` records at the current step without advancing, so
        the next call shares it. A call whose every value is dropped as
        non-numeric consumes no step.
        """
        entry = sanitize_entry(create_log_entry("metrics", values=dict(mapping)))
        if entry is None:
            return
        entry["step"] = self._steps.take(step, commit)
        self._log_buffer.append(entry)

    def _log_unstepped(self, mapping):
        """System metrics: sampled on the clock, not on the training step."""
        self._append(create_log_entry("metrics", values=dict(mapping)))
