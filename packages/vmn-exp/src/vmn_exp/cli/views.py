#!/usr/bin/env python3
"""Rows and machine-readable payloads for ``vmn-exp list`` / ``vmn-exp show``.

A list row is exactly what ``vmn_exp.sdk.reader.list_runs`` returns: the
index row, its derived status fields and its place in the run tree. ``show
--json`` adds the run's metadata, patch sizes and (the tail of) its log.
Non-finite metrics are written as ``null`` so the output is strict JSON.
"""
import json
import math

from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.log import experiment_row
from vmn_exp.core.media import media_counts
from vmn_exp.core.record_format import record_format_version
from vmn_exp.core.status import status_fields

PATCH_TYPES = ("working_tree", "local_commits")



def metrics_schema(vcs):
    """``experiment.metrics`` from the app's conf.yml, if any: sort direction
    and summary policies (see :mod:`vmn_exp.core.metric_summary`)."""
    return experiment_conf(vcs).get("metrics") or {}


def patch_lines(patches):
    """``{patch type: line count}`` for the patches present."""
    return {p: patches[p].count("\n") for p in PATCH_TYPES if (patches or {}).get(p)}


def show_payload(
    idx, metadata, patches, log, run_state, tree, log_tail=None, observed_at=None,
    schema=None,
):
    """The ``show --json`` object; *log_tail* keeps only the newest entries.
    *schema* is the app's metrics schema."""
    run = experiment_row(idx, metadata, log, schema=schema)
    run.update(status_fields(run_state, observed_at=observed_at))
    run.update(tree)
    run["base_commit"] = metadata.get("base_commit")
    run["format_version"] = record_format_version(metadata)
    run["has_dep_patches"] = bool(metadata.get("has_dep_patches"))
    run["patches"] = patch_lines(patches)
    run["log"] = log[-log_tail:] if log_tail else log
    run["log_total"] = len(log)
    run["media_counts"] = media_counts(log)
    return run


def format_number(value):
    """A metric value for display: floats to 4 significant digits."""
    return f"{value:.4g}" if isinstance(value, float) else str(value)


def format_metric_lines(metrics, summary):
    """``name: value`` per metric, name-ordered; a metric whose last, min and
    max differ adds them: ``loss: 0.2 (last 0.9, min 0.2, max 1)``."""
    lines = []
    for name, value in sorted(metrics.items()):
        line = f"{name}: {format_number(value)}"
        parts = summary.get(name)
        if parts and len({format_number(v) for v in parts.values()}) > 1:
            line += " (" + ", ".join(
                f"{k} {format_number(parts[k])}" for k in ("last", "min", "max")
            ) + ")"
        lines.append(line)
    return lines


def _finite_or_none(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite_or_none(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite_or_none(v) for v in value]
    return value


def dumps(payload):
    """Strict, stable JSON: sorted keys, NaN/inf as ``null``."""
    return json.dumps(
        _finite_or_none(payload), indent=2, sort_keys=True, allow_nan=False, default=str
    )
