#!/usr/bin/env python3
"""Custom x axes: a metric charted against another metric instead of the step.

``run.define_metric("val_*", step_metric="epoch")`` appends a
``define_metric`` log entry::

    {"type": "define_metric", "name": "val_*", "step_metric": "epoch", ...}

*name* is an exact metric name or an ``fnmatch`` glob. Entries fold per name,
last write wins per field, and any extra fields ride along untouched. The
app's conf.yml can declare the same thing in its metrics schema
(``experiment.metrics.<name>.step_metric``, next to ``goal:``); a run's own
declarations win over the schema, and an exact name over a glob.

A joined point is the metric's point plus ``x``: the x metric's value logged
at the same step — or, for step-less points, in the same ``log_metrics`` call
(the same timestamp). A point with no finite x is dropped.

Pure functions over plain data, like the rest of ``core``.
"""
from fnmatch import fnmatchcase

from vmn_exp.core.values import is_finite_number
from vmn_exp.core.writer import create_log_entry

DEFINE_METRIC = "define_metric"


def create_define_metric_entry(name, step_metric=None, **fields):
    """A ``define_metric`` log entry, or ValueError on a bad name."""
    if not isinstance(name, str) or not name:
        raise ValueError(f"Metric name must be a non-empty string, got {name!r}")
    if step_metric is not None:
        if not isinstance(step_metric, str) or not step_metric:
            raise ValueError(f"step_metric must be a metric name, got {step_metric!r}")
        fields["step_metric"] = step_metric
    return create_log_entry(DEFINE_METRIC, name=name, **fields)


def metric_definitions(log, into=None):
    """``{name: {field: value}}`` from a log's ``define_metric`` entries,
    folded into *into* when given."""
    defs = {} if into is None else into
    for entry in log:
        if entry.get("type") != DEFINE_METRIC or not isinstance(entry.get("name"), str):
            continue
        fields = {k: v for k, v in entry.items() if k not in ("type", "name", "timestamp")}
        fields.pop("_writer", None)
        defs.setdefault(entry["name"], {}).update(fields)
    return defs


def _step_of(declaration):
    return (declaration or {}).get("step_metric")


def lookup(metric, declarations, pick=_step_of):
    """What *pick* reads from the declaration *declarations* give *metric*:
    the exact name's, else the latest-declared matching glob's."""
    exact = pick(declarations.get(metric))
    if exact:
        return exact
    for pattern in reversed(list(declarations)):
        found = pick(declarations[pattern])
        if found and fnmatchcase(metric, pattern):
            return found
    return None


def declared_step_metric(metric, definitions=None, schema=None):
    """The x metric declared for *metric* (run definitions, then the conf
    schema), or None. A metric is never its own x."""
    for declarations in (definitions or {}, schema or {}):
        step = lookup(metric, declarations)
        if step:
            return None if step == metric else step
    return None


def step_metrics(keys, definitions=None, schema=None):
    """``{metric: x metric}`` for those of *keys* that declare one."""
    found = {k: declared_step_metric(k, definitions, schema) for k in keys}
    return {k: v for k, v in found.items() if v}


def _join_key(point):
    step = point.get("step")
    return ("step", step) if step is not None else ("ts", point.get("ts"))


def join_series(points, x_points):
    """*points* with ``x`` from *x_points* at the same step; unmatched dropped."""
    x_at = {_join_key(p): p.get("value") for p in x_points}
    joined = []
    for point in points:
        x = x_at.get(_join_key(point))
        if is_finite_number(x):
            joined.append(dict(point, x=x))
    return joined


def join_all(series, x):
    """Every metric of *series* but *x*, joined on *x*."""
    x_points = series.get(x, [])
    return {k: join_series(v, x_points) for k, v in series.items() if k != x}
