#!/usr/bin/env python3
"""``run.define_metric``: declare how a metric (or a glob of them) is charted
and ranked.

Kept apart from :mod:`vmn_exp.sdk.run` so other per-metric declarations can
compose into the same call; every keyword lands in the ``define_metric`` log
entry (see :mod:`vmn_exp.core.step_metric` and
:mod:`vmn_exp.core.metric_summary`).
"""
from vmn_exp.core.metric_summary import summary_fields
from vmn_exp.core.step_metric import create_define_metric_entry


class MetricDefinitions:
    """Mixin for :class:`~vmn_exp.sdk.run.Run`; needs ``self._append``."""

    def define_metric(self, name, step_metric=None, summary=None, goal=None, **fields):
        """Declare metric *name* (exact or an ``fnmatch`` glob like ``val_*``).

        *step_metric* names the metric its charts use as the x axis: points
        are joined on the step, so log both in the same step (typically the
        same ``log_metrics`` call)::

            run.define_metric("val_*", step_metric="epoch")
            run.log_metrics({"val_loss": 0.3, "epoch": 2}, step=step)

        *summary* (``"min"``, ``"max"`` or ``"last"``; default from *goal*,
        ``"min"``/``"max"``) is the value the run ranks on in every reader —
        ``row["metrics"][name]`` — beating the app's conf.yml schema::

            run.define_metric("val_loss", goal="min")  # rank on the best epoch

        Later declarations of the same *name* override earlier ones per field.
        """
        fields.update(summary_fields(summary, goal))
        self._append(create_define_metric_entry(name, step_metric=step_metric, **fields))
