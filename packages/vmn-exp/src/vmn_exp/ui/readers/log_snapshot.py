#!/usr/bin/env python3
"""One poll's view of a record's parsed log (:mod:`parsed_logs`): a fixed
prefix of entries that later growth never changes."""
from itertools import islice

from vmn_exp.core.fold import (
    fold_definitions,
    fold_last_metric_at,
    fold_metrics,
    fold_rewinds,
    fold_values,
)
from vmn_exp.core.metric_schema import hidden_metrics, metric_charts
from vmn_exp.core.step_metric import join_on, step_metrics, x_lookup
from vmn_exp.ui.readers.series import downsample

# The most steps run detail lists of one bars/table metric (the latest kept).
MAX_HINTED_STEPS = 5000


def _metric_parts(fold):
    """What :func:`fold_metrics` reads, copied at this poll: the fold itself
    keeps growing under a snapshot."""
    return {
        "metrics": dict(fold["metrics"]),
        "extrema": dict(fold.get("extrema") or {}),
        "firsts": dict(fold.get("firsts") or {}),
        "metric_defs": {n: dict(f) for n, f in (fold.get("metric_defs") or {}).items()},
    }


class LogSnapshot:
    """One poll's view of a parsed log: the first ``total`` entries."""

    def __init__(self, parsed):
        self._parsed = parsed
        self._entries = parsed.entries
        self.total = len(parsed.entries)
        self._series = parsed.series
        self._counts = dict(parsed.counts)
        self.params = fold_values(parsed.fold, "params")
        self.metrics = fold_values(parsed.fold, "metrics")
        self._metric_fold = _metric_parts(parsed.fold)
        self.last_metric_at = fold_last_metric_at(parsed.fold)
        self.media = parsed.media_view
        # The fold keys a rewind by its log position (see fold_log).
        self._rewinds = [(r[0], r[1]) for r in fold_rewinds(parsed.fold)]
        self.memo = {}  # derived views (thinned series) of this exact snapshot

    def summarized_metrics(self, schema=None):
        """``(metrics, metric_summary)`` under the metrics *schema* — see
        :func:`~vmn_exp.core.fold.fold_metrics`."""
        return fold_metrics(self._metric_fold, schema)

    def step_metrics(self, schema=None):
        """``{metric: x metric}`` the run's definitions and *schema* declare."""
        return step_metrics(self._counts, fold_definitions(self._metric_fold), schema)

    def hidden_metrics(self, schema=None):
        """The run's metrics its definitions, else *schema*, mark hidden."""
        names = {*self.metrics, *self._counts}
        return hidden_metrics(names, fold_definitions(self._metric_fold), schema)

    def metric_charts(self, schema=None):
        """``{metric: chart}`` of the run's metrics not drawn as a line."""
        names = {*self.metrics, *self._counts}
        return metric_charts(names, fold_definitions(self._metric_fold), schema)

    def metric_steps(self, charts):
        """``{metric: {"rows": [{step, value}], "total"}}`` of the *charts*
        metrics: the last value logged at each step, steps ascending
        (step-less last), from every point (never thinned); the latest
        :data:`MAX_HINTED_STEPS` steps of ``total``."""
        key = ("metric_steps", tuple(sorted(charts)), MAX_HINTED_STEPS)
        if key not in self.memo:
            self.memo[key] = {m: _last_per_step(self._points(m)) for m in sorted(charts)}
        return self.memo[key]

    def log(self):
        return self._entries[: self.total]

    def rewinds(self):
        """``[{"step", "timestamp"}]`` of the log's rewinds, in log order."""
        return [
            {"step": step, "timestamp": self._entries[pos].get("timestamp")}
            for step, pos in self._rewinds
        ]

    def tail(self, n):
        return self._entries[max(self.total - n, 0) : self.total]

    def page(self, offset, limit):
        offset = max(offset, 0)
        return self._entries[offset : min(offset + max(limit, 0), self.total)]

    def series_keys(self):
        return self._counts.keys()

    def last_step(self):
        """The highest step among the metrics' newest points, or None."""
        steps = (self._series[k][n - 1].get("step") for k, n in self._counts.items() if n)
        return max((s for s in steps if isinstance(s, (int, float))), default=None)

    def series(self, keys=None):
        """``{metric: [points]}`` — every metric, or those of *keys* it has."""
        names = self._counts if keys is None else [k for k in keys if k in self._counts]
        return {k: self._series[k][: self._counts[k]] for k in names}

    def thinned(self, keys, max_points):
        """``(series, series_total)`` of *keys* it has, each thinned to
        *max_points* — extending the record's thinners, so a grown series
        costs its new points."""
        names = [k for k in keys if k in self._counts]
        with self._parsed.thin_lock:
            series = {
                k: self._parsed.thinner(k, max_points).thin(self._series[k], self._counts[k])
                for k in names
            }
        return series, {k: self._counts[k] for k in names}

    def _points(self, key):
        """*key*'s points this snapshot sees, without copying them."""
        return islice(self._series[key], self._counts[key]) if key in self._counts else ()

    def joined(self, x_of, max_points):
        """``(series, series_total)`` of each metric of *x_of* joined on its x
        metric (see :func:`~vmn_exp.core.step_metric.join_series`), then
        thinned to *max_points*."""
        lookups = {x: x_lookup(self._points(x)) for x in set(x_of.values())}
        joined = {k: join_on(self._points(k), lookups[x]) for k, x in x_of.items()}
        return (
            {k: downsample(v, max_points) for k, v in joined.items()},
            {k: len(v) for k, v in joined.items()},
        )


def _step_order(step):
    return (1, 0) if step is None else (0, step)


def _last_per_step(points):
    last = {}
    for point in points:
        last[point.get("step")] = point.get("value")
    steps = sorted(last, key=_step_order)
    return {
        "rows": [{"step": s, "value": last[s]} for s in steps[-MAX_HINTED_STEPS:]],
        "total": len(steps),
    }
